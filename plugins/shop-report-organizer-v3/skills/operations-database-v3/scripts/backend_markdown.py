"""Convert recognized shop-metric Markdown tables without calculating metrics."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

BACKEND_DIR = "7.后台数据库"
CATEGORIES = {"成交金额（元）": "交易概况", "综合体验星级": "体验与差评", "店铺访客数（人）": "流量数据"}


def cells(line):
    return [v.strip().replace(r"\|", "|") for v in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def parse(path):
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    shop_match = re.search(r"(?:^|\n)[ \t]*(?:[-*+]\s+)?店铺[：:][ \t]*([^。\n]+)", text)
    if not shop_match:
        raise ValueError("MD缺少明确店铺名称，保留原位")
    shop = shop_match.group(1).strip()
    # A short table date needs one explicit reporting year, never the system year.
    reporting_dates = re.findall(r"(?:^|\n)[ \t]*(?:[-*+]\s+)?统计日期[：:][ \t]*(20\d{2}-\d{2}-\d{2})", text)
    reporting_years = {dt.date.fromisoformat(value).year for value in reporting_dates}
    scope_match = re.search(r"只排除(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    scope = dt.date(*(int(v) for v in scope_match.groups())).isoformat() if scope_match else None
    product_match = re.search(r"商品ID\s*\*{0,2}(\d{6,})", text)
    excluded_id = product_match.group(1) if product_match else None
    lines = text.splitlines()
    tables = []
    dates = set()
    consumed = set()
    index = 0
    seen = set()
    historical_section = False
    while index + 1 < len(lines):
        if re.match(r"^##\s+", lines[index]):
            historical_section = lines[index].strip() == "## 日期不匹配的历史截图数据（不计入本周）"
        if not lines[index].lstrip().startswith("|") or not re.fullmatch(r"[| :\-]+", lines[index+1].strip()):
            index += 1
            continue
        header = cells(lines[index])
        name = next((kind for field, kind in CATEGORIES.items() if field in header), None)
        historical = historical_section and name in {"交易概况", "流量数据"}
        if historical:
            name = {"交易概况": "历史截图转录（交易）", "流量数据": "历史截图转录（流量）"}[name]
        supplemental = False
        if not name:
            if header == ["指标", "店铺/商品汇总原值", "排除商品值", "直接扣减后"]:
                name = "商品排除扣减（估算）"
            elif header == ["指标", "调整值", "计算口径"]:
                name = "商品排除指标（估算）"
            elif header == ["日期", "需要补充", "缺少的指标/条件"]:
                name = "待补核对"
            if name:
                supplemental = True
                if not scope or not excluded_id:
                    raise ValueError("商品排除附表缺少明确的唯一排除日期或商品ID，保留原位")
        if not name or (not supplemental and "日期" not in header):
            raise ValueError("MD含未支持的表格字段，保留原位以免遗漏数据")
        if name in seen or len(header) != len(set(header)):
            raise ValueError("MD表格分类或表头重复，需确认后整理")
        seen.add(name)
        consumed.update((index, index+1))
        index += 2
        values = []
        seen_dates = set()
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            row = cells(lines[index])
            if len(row) != len(header):
                raise ValueError(f"MD第{index+1}行列数与表头不一致")
            if supplemental:
                key = tuple(row[:1])
                if key in seen_dates:
                    raise ValueError(f"{name}存在重复指标或日期，停止自动合并")
                seen_dates.add(key)
            else:
                date = row[header.index("日期")]
                if re.fullmatch(r"\d{2}-\d{2}", date):
                    if len(reporting_years) != 1:
                        raise ValueError("表内简写日期缺少唯一明确统计年份，保留原位")
                    date = f"{next(iter(reporting_years))}-{date}"
                    if date not in reporting_dates:
                        raise ValueError("表内简写日期与明确统计日期不一致，保留原位")
                    row[header.index("日期")] = date
                dt.date.fromisoformat(date)
                if date in seen_dates:
                    raise ValueError(f"{name}存在重复日期{date}，停止自动合并")
                seen_dates.add(date)
                if not historical:
                    dates.add(date)
                # Normalize presentation only; preserve the original bytes in the MD archive.
                row = [re.sub(r"\s+([星分])$", r"\1", value) for value in row]
                row = [value.replace(",", "") if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value) else value for value in row]
            values.append(row)
            consumed.add(index)
            index += 1
        if not values:
            raise ValueError(f"{name}没有数据行")
        if supplemental:
            header = ["适用日期", "排除商品ID", "数据口径"] + header
            values = [[scope, excluded_id, "用户MD分析记录；直接扣减/非去重估算，非平台实测，不计入原始指标"] + row for row in values]
        if historical:
            header = header + ["数据口径"]
            values = [row + ["历史截图文字转录；未核对其他历史记录，不计入本周指标"] for row in values]
        tables.append({"name": name, "headers": header, "rows": values})
    if not tables:
        raise ValueError("未识别后台交易/体验/流量指标Markdown表格")
    if not dates:
        raise ValueError("只有历史截图附表，缺少本期指标日期，保留原位")
    if scope and any(t["name"].endswith("（估算）") for t in tables) and scope not in dates:
        raise ValueError("分析适用日期不在原始指标日期中，停止归档")
    # All narrative is evidence, never commands to execute or claims to verify here.
    notes = [line for n, line in enumerate(lines) if n not in consumed and line.strip()]
    return {"shop": shop, "start": min(dates), "end": max(dates), "tables": tables,
            "notes": notes, "source_name": path.name, "sha256": hashlib.sha256(raw).hexdigest()}


def safe(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).rstrip(". ") or "未命名"


def target_for(root, data):
    end = data["end"]
    folder = root / BACKEND_DIR / safe(data["shop"]) / (end[:4]+"年") / (end[5:7]+"月")
    # Immutable snapshots avoid silently overwriting a correction or another source.
    return folder / (f'后台数据_{data["start"]}至{end}_{data["sha256"][:12]}.xlsx')


def runtime():
    deps = Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies"
    node = Path(os.environ.get("BACKEND_METRICS_NODE", str(deps/"node/bin/node.exe")))
    modules = Path(os.environ.get("BACKEND_METRICS_NODE_MODULES", str(deps/"node/node_modules")))
    if not node.is_file() or not (modules/"@oai/artifact-tool").is_dir():
        raise RuntimeError("缺少内置Node或artifact-tool，源MD保留原位")
    return node, modules


def apply(path, root, data):
    target = target_for(root, data)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = data["sha256"]
    original = target.parent/"原始记录"/(safe(path.stem)+"_"+digest[:12]+".md")
    audit = target.with_suffix(".archive.json")
    if target.exists():
        if not audit.exists() or json.loads(audit.read_text(encoding="utf-8"))["sha256"] != digest:
            raise RuntimeError("目标文件已存在但归档凭据不一致，保留源文件")
        receipt = json.loads(audit.read_text(encoding="utf-8"))
        if hashlib.sha256(target.read_bytes()).hexdigest() != receipt.get("workbook_sha256"):
            raise RuntimeError("已有Excel与归档哈希不一致，保留源文件")
        verify_workbook(target, data)
        if not original.exists() or hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            raise RuntimeError("原始MD归档缺失或发生变更，保留源文件")
    else:
        node, modules = runtime()
        with tempfile.TemporaryDirectory(prefix=".backend-md-", dir=target.parent) as temp:
            temp = Path(temp)
            payload = temp/"payload.json"
            payload.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            output = temp/"后台数据.xlsx"
            env = dict(os.environ, BACKEND_METRICS_NODE_MODULES=str(modules))
            completed = subprocess.run([str(node), str(Path(__file__).with_name("write_backend_workbook.mjs")),
                                        str(payload), str(output)], env=env, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=180)
            if completed.returncode != 0 or not output.is_file():
                raise RuntimeError("后台表格生成失败，源MD保留："+completed.stderr[-1500:])
            verify_workbook(output, data)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError("整理期间源MD发生变更，保留源文件")
            original.parent.mkdir(exist_ok=True)
            if original.exists() and original.read_bytes() != path.read_bytes():
                raise RuntimeError("原始记录文件冲突，停止归档")
            shutil.copy2(path, original)
            if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
                raise RuntimeError("MD归档哈希不一致，保留源文件")
            os.replace(output, target)
            receipt = {**{k: data[k] for k in ("shop", "start", "end", "source_name", "sha256")},
                       "original": str(original), "workbook_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                       "row_counts": {t["name"]:len(t["rows"]) for t in data["tables"]},
                       "business_calculations": "仅新老买家数推算"}
            audit.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            qa = root/"_系统/后台表格预览"/digest[:12]
            images = list(temp.glob("*.png"))
            if images:
                qa.mkdir(parents=True, exist_ok=True)
                for image in images:
                    shutil.copy2(image, qa/image.name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError("源MD已变更，保留原位")
    path.unlink()
    return target


def verify_workbook(path, data):
    """Read-only independent validation: every metric, missing marker and note."""
    import openpyxl
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        for table in data["tables"]:
            sheet = workbook[table["name"]]
            actual = list(sheet.values)
            assert len(actual) == len(table["rows"])+1, table["name"]
            expected_headers = table["headers"] + (["新买家数", "老买家数"] if table["name"] == "交易概况" else [])
            assert list(actual[0]) == expected_headers
            for source, output in zip(table["rows"], actual[1:]):
                for col, (raw, value) in enumerate(zip(source, output)):
                    header = table["headers"][col]
                    if header in {"日期", "适用日期"} and re.fullmatch(r"20\d{2}-\d{2}-\d{2}",raw):
                        assert str(value)[:10] == raw
                    elif header == "排除商品ID":
                        assert str(value) == raw
                    elif raw in {"", "待补", "未知", "-", "n.a."}:
                        assert value == (raw or None)
                    elif re.fullmatch(r"-?\d+(?:\.\d+)?%", raw):
                        assert abs(float(value)-float(raw[:-1])/100)<1e-12
                    elif re.fullmatch(r"-?\d+(?:\.\d+)?(?:星|分)?", raw):
                        assert abs(float(value)-float(raw.rstrip("星分")))<1e-10
                    else:
                        assert value == raw
        assert workbook.sheetnames == [table["name"] for table in data["tables"]], "Excel只能保存指标工作表"
        from openpyxl.utils import get_column_letter
        from decimal import Decimal, ROUND_HALF_UP
        cached = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            allowed = set()
            for table in data["tables"]:
                if table["name"] != "交易概况": continue
                total_col = get_column_letter(next(i for i,h in enumerate(table["headers"]) if h in {"成交买家数","成交买家数（人）"})+1)
                share_col = get_column_letter(next(i for i,h in enumerate(table["headers"]) if h in {"老买家占比","成交老买家占比"})+1)
                new_col = get_column_letter(len(table["headers"])+1)
                old_col = get_column_letter(len(table["headers"])+2)
                ws = workbook[table["name"]]
                values = list(cached[table["name"]].values)
                for index, raw in enumerate(table["rows"], 2):
                    allowed.update({(ws.title,f"{new_col}{index}"),(ws.title,f"{old_col}{index}")})
                    assert ws[f"{old_col}{index}"].data_type == "f"
                    assert f"ROUND({total_col}{index}*{share_col}{index},0)" in ws[f"{old_col}{index}"].value
                    assert f"{total_col}{index}-{old_col}{index}" in ws[f"{new_col}{index}"].value
                    buyer = raw[next(i for i,h in enumerate(table["headers"]) if h in {"成交买家数","成交买家数（人）"})]
                    share = raw[next(i for i,h in enumerate(table["headers"]) if h in {"老买家占比","成交老买家占比"})]
                    if re.fullmatch(r"\d+",buyer) and re.fullmatch(r"\d+(?:\.\d+)?%",share) and Decimal(share[:-1])<=100:
                        old = int((Decimal(buyer)*Decimal(share[:-1])/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                        assert values[index-1][-2:] == (int(buyer)-old,old)
                    else:
                        assert values[index-1][-2:] == ("待补","待补")
            assert all((s.title,c.coordinate) in allowed for s in workbook for row in s for c in row if c.data_type == "f")
        finally:
            cached.close()
    finally:
        workbook.close()


def process(root, input_dir, apply_mode=False):
    rows = []
    plans = []
    for path in sorted(input_dir.glob("*.md")):
        try:
            data = parse(path)
            plans.append((path, data))
            rows.append({"source":str(path), "status":"ready", "shop":data["shop"],
                         "period":data["start"]+"至"+data["end"], "target":str(target_for(root,data)),
                         "rows":json.dumps({t["name"]:len(t["rows"]) for t in data["tables"]},ensure_ascii=False),
                         "message":"转换归档，并按成交买家数及老买家占比推算新老买家数；不保存来源说明工作表"})
        except (ValueError, UnicodeError) as exc:
            rows.append({"source":str(path), "status":"pending", "message":str(exc)})
    if apply_mode and not any(r["status"]=="pending" for r in rows):
        for path, data in plans:
            apply(path, root, data)
    log = root/"5.运营操作日志"/("后台MD整理记录.csv" if apply_mode else "后台MD整理记录_预览.csv")
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=["source","status","shop","period","target","rows","message"])
        writer.writeheader();writer.writerows(rows)
    print(json.dumps(rows,ensure_ascii=False,indent=2))
    print("后台MD："+("正式转换归档完成" if apply_mode and all(r["status"]=="ready" for r in rows) else "仅预览或存在待确认项"))
    return 1 if any(r["status"]=="pending" for r in rows) else 0


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--database-root",required=True)
    parser.add_argument("--input")
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--apply",action="store_true")
    mode.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    root=Path(args.database_root).resolve()
    raise SystemExit(process(root,Path(args.input) if args.input else root/"下载未分类",args.apply))
