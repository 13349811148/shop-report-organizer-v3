"""Recognize and archive JD platform exports without changing the source tables."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


SKU_KIND = "京东SKU原表"
ORDER_KIND = "京东订单原表"
AFTER_SALE_KIND = "京东售后原表"
PROMOTION_KIND = "京准通推广明细"
CASH_KIND = "京准通现金消费"
VOUCHER_KIND = "京准通红包消费"
SHOP_SUFFIX = "（京东）"
PASSWORD_ENV = "OPS_V3_JD_ORDER_PASSWORD"
ORDER_HEADERS = ("订单号", "商品ID", "商品名称", "订购数量", "下单时间", "京东价", "商家应收", "订单状态", "付款确认时间")
SHOP_LABEL = r"(?P<shop>[^\\/:*?\"<>|\r\n]+?)[（(]京东[）)]"
FINANCE_HEADERS = ("流水单号", "投放账户名称", "投放账户ID", "投放日期", "交易类型", "支出", "秒送门店ID")
CASH_HEADERS = ("结算时间", "结余", "开票方式")


@dataclass(frozen=True)
class Report:
    kind: str
    report_type: str
    headers: tuple[str, ...]
    date_header: str = ""
    sku_header: str = ""


ORDER_REPORT = Report(ORDER_KIND, "订单数据", ORDER_HEADERS, "下单时间", "商品ID")
REPORTS = (
    ORDER_REPORT,
    Report(SKU_KIND, "商品数据", ("SKUID", "商品编码", "商品名称", "商家SKU", "商品链接", "短标题"), sku_header="SKUID"),
    Report(
        AFTER_SALE_KIND, "售后数据",
        ("服务单号", "客户期望", "售后状态", "售后申请时间", "申请时订单状态", "商品编号", "退款金额"),
        "售后申请时间", "商品编号",
    ),
    Report(
        PROMOTION_KIND, "推广数据",
        ("日期", "产品线", "单元ID", "创意ID", "智能投放推广SKU ID", "展现数", "点击数", "花费"),
        "日期", "智能投放推广SKU ID",
    ),
    Report(CASH_KIND, "推广数据", FINANCE_HEADERS + CASH_HEADERS, "投放日期"),
    Report(VOUCHER_KIND, "推广数据", FINANCE_HEADERS, "投放日期"),
)


def match_report(rows):
    for index, headers in enumerate(rows[:20]):
        columns = {value: pos for pos, value in enumerate(headers) if value}
        for report in REPORTS:
            if not all(field in columns for field in report.headers):
                continue
            if report.kind == VOUCHER_KIND and any(field in columns for field in CASH_HEADERS):
                continue
            return report, index, columns
    return None


def normalize_shop_label(value: str) -> str:
    match = re.fullmatch(SHOP_LABEL, value.strip())
    if not match or not match["shop"].strip():
        return ""
    return match["shop"].strip() + SHOP_SUFFIX


def named_shop(source: Path, report: Report) -> str:
    if report.kind == SKU_KIND:
        match = re.fullmatch(r"导出商品普通POP-SKU信息_\d+_\d+\s+(.+)", source.stem)
        return normalize_shop_label(match[1]) if match else ""
    if report.kind == PROMOTION_KIND:
        match = re.fullmatch(r"(.+?)_20\d{2}-\d{2}-\d{2}_\d{2}-\d{2}自定义报表_\d{8}_\d{8}_.+", source.stem)
        if match:
            label = match[1]
            return normalize_shop_label(label) or normalize_shop_label(label + SHOP_SUFFIX)
    return ""


def make_analysis(source, report, download_date, o, *, reason="missing_required_fields",
                  period="", shop="", ids=(), missing="shop_name", digest=""):
    return o.Analysis(
        source=source, status="pending", reason=reason, report_type=report.report_type,
        target_folder=o.REPORT_ROOT_BY_TYPE[report.report_type], shop_name=shop,
        shop_source="jd_export_shop_label" if shop else "", period=period,
        period_source=("download_date" if report.kind == SKU_KIND else "date_column") if period else "",
        download_date=download_date.isoformat(), target_path=source, product_counts="",
        matched_headers="|".join(report.headers), missing_fields=missing, map_updates=[],
        product_ids=sorted(ids), new_product_ids=[], jd_kind=report.kind, jd_sha256=digest,
    )


def analyze(source, rows, download_date, o, max_rows, max_cols, *, encrypted=False):
    matched = match_report(rows)
    if not matched:
        return None
    if not encrypted and len(rows) >= max_rows:
        rows = list(o.iter_rows_full(source, max_cols))
        matched = match_report(rows)
        if matched is None:
            raise RuntimeError(f"京东报表表头发生变化：{source.name}")
    report, index, columns = matched
    id_index = columns.get(report.sku_header)
    date_index = columns.get(report.date_header)
    date_values = set()
    ids = set()
    invalid_dates = 0
    for row in rows[index + 1:]:
        if not any(row) or o.is_ignorable_order_row(row):
            continue
        if id_index is not None and id_index < len(row):
            sku = o.normalize_product_id(row[id_index])
            if sku:
                ids.add(sku)
        if date_index is not None:
            value = o.parse_date(row[date_index]) if date_index < len(row) else None
            if value is None:
                invalid_dates += 1
            else:
                date_values.add(value)
    period = download_date.isoformat() if report.kind == SKU_KIND else ""
    if date_values and not invalid_dates:
        period = f"{min(date_values).isoformat()}至{max(date_values).isoformat()}"
    missing = []
    if not period:
        missing.append("period")
    if report.kind == SKU_KIND and not ids:
        missing.append("SKUID")
    shop = named_shop(source, report)
    item = make_analysis(
        source, report, download_date, o, period=period, shop=shop, ids=ids,
        missing="|".join(missing), digest=o.file_sha256(source),
    )
    item.jd_encrypted = encrypted
    return item


def encrypted_order(source, download_date, o, max_rows, max_cols):
    if source.suffix.lower() != ".xlsx" or not re.fullmatch(
        r"订单明细信息--20\d{2}(?:-\d{2}){5}-TO-20\d{2}(?:-\d{2}){5}--\d+(?:_\d+)?", source.stem
    ):
        return None
    with source.open("rb") as stream:
        if stream.read(8) != bytes.fromhex("d0cf11e0a1b11ae1"):
            return None
        body = stream.read()
    if not all(label.encode("utf-16le") in body for label in ("EncryptionInfo", "EncryptedPackage")):
        return None
    if not os.environ.get(PASSWORD_ENV):
        return make_analysis(
            source, ORDER_REPORT, download_date, o,
            reason="京东订单工作簿有打开密码，请提供本次工作簿密码或 Excel 解密副本",
            missing="workbook_password",
        )
    try:
        rows = read_encrypted_order(source, o)
    except (OSError, ValueError, subprocess.SubprocessError):
        return make_analysis(
            source, ORDER_REPORT, download_date, o,
            reason="Excel 无法用本次密码读取京东订单工作簿，请核对密码或使用解密副本",
            missing="workbook_password",
        )
    matched = match_report(rows)
    if not matched or matched[0] != ORDER_REPORT:
        return make_analysis(
            source, ORDER_REPORT, download_date, o,
            reason="京东订单已打开，表头与订单明细格式不匹配",
            missing="order_header",
        )
    return analyze(source, rows, download_date, o, max_rows, max_cols, encrypted=True)


def read_encrypted_order(source, o):
    env = os.environ.copy()
    env["OPS_V3_JD_ORDER_PATH"] = str(source)
    env["OPS_V3_JD_ORDER_HEADERS"] = "|".join(ORDER_HEADERS)
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$headers = $env:OPS_V3_JD_ORDER_HEADERS.Split('|')
$excel = New-Object -ComObject Excel.Application
$book = $null
try {
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $excel.AutomationSecurity = 3
  $excel.EnableEvents = $false
  $book = $excel.Workbooks.Open($env:OPS_V3_JD_ORDER_PATH, 0, $true, [Type]::Missing, $env:OPS_V3_JD_ORDER_PASSWORD)
  $result = [System.Collections.Generic.List[object]]::new()
  foreach ($sheet in $book.Worksheets) {
    $range = $sheet.UsedRange
    $values = $range.Value2
    if ($values -isnot [array] -or $values.Rank -ne 2) { continue }
    $firstRow = $values.GetLowerBound(0)
    $firstCol = $values.GetLowerBound(1)
    $columns = @{}
    for ($col = $firstCol; $col -le $values.GetUpperBound(1); $col++) {
      $columns[[string]$values[$firstRow,$col]] = $col
    }
    if (@($headers | Where-Object { !$columns.ContainsKey($_) }).Count -gt 0) { continue }
    if ($result.Count -eq 0) { $result.Add($headers) }
    for ($row = $firstRow + 1; $row -le $values.GetUpperBound(0); $row++) {
      $cells = @(
        foreach ($header in $headers) {
          $value = $values[$row, $columns[$header]]
          if ($header -in '下单时间','付款确认时间' -and $value -is [double] -and $value -gt 0) {
            $serial = if ($book.Date1904) { $value + 1462 } else { $value }
            [DateTime]::FromOADate($serial).ToString('yyyy-MM-dd HH:mm:ss')
          } else {
            [string]$value
          }
        }
      )
      $result.Add($cells)
    }
  }
  ConvertTo-Json -InputObject $result.ToArray() -Depth 4 -Compress
} finally {
  if ($book) { $book.Close($false) }
  $excel.Quit()
  [Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
"""
    result = subprocess.run(
        [o.powershell_exe(), "-NoProfile", "-Command", script], env=env, timeout=120,
        capture_output=True, check=True, encoding="utf-8",
    )
    return [[o.normalize_text(cell) for cell in row] for row in json.loads(result.stdout)]


def sku_owners(root, analyses, o, max_rows, max_cols):
    owners = defaultdict(set)
    product_root = root / o.REPORT_ROOT_BY_TYPE["商品数据"]
    for shop_dir in product_root.iterdir():
        if not shop_dir.is_dir() or not normalize_shop_label(shop_dir.name):
            continue
        for path in (shop_dir / SKU_KIND).rglob("*.xlsx"):
            receipt_path = path.with_name(path.name + ".archive.json")
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt["shop"] != shop_dir.name or receipt["sha256"] != o.file_sha256(path):
                    continue
                item = analyze(path, o.read_rows(path, max_rows, max_cols), o.download_date(path), o, max_rows, max_cols)
            except (OSError, ValueError, RuntimeError, KeyError):
                continue
            if item and item.jd_kind == SKU_KIND:
                for sku in item.product_ids:
                    owners[sku].add(shop_dir.name)
    for item in analyses:
        if item.jd_kind == SKU_KIND and item.shop_name and not item.missing_fields:
            for sku in item.product_ids:
                owners[sku].add(item.shop_name)
    return owners


def resolve_batch(root, analyses, scoped_shop, o, max_rows, max_cols):
    jd = [item for item in analyses if item.jd_kind]
    if not jd:
        return
    owners = sku_owners(root, jd, o, max_rows, max_cols)
    for item in jd:
        if item.missing_fields in {"workbook_password", "order_header"}:
            continue
        missing = item.missing_fields.split("|") if item.missing_fields else []
        counts = Counter(shop for sku in item.product_ids for shop in owners.get(sku, ()))
        item.product_counts = "|".join(f"{shop}:{count}" for shop, count in sorted(counts.items()))
        if item.jd_kind == SKU_KIND:
            # SKU 商品本身可以由多个京东店销售，以显式店名归档商品原表。
            if not item.shop_name and scoped_shop:
                item.shop_name, item.shop_source = scoped_shop, "jd_shop_argument"
        else:
            evidence = set(counts) | {name for name in (item.shop_name, scoped_shop) if name}
            if len(evidence) > 1:
                item.shop_name = ""
                item.shop_source = "conflicting_jd_shop_evidence"
                item.reason = "京东店铺标签、SKU 或指定店铺的归属冲突"
                missing.append("shop_conflict")
            elif evidence and not item.shop_name:
                item.shop_name = next(iter(evidence))
                item.shop_source = "jd_sku_map" if counts else "jd_shop_argument"
        if not item.shop_name and "shop_conflict" not in missing:
            missing.append("shop_name")
        if missing:
            item.missing_fields = "|".join(missing)
            continue
        year, month, _ = item.download_date.split("-")
        item.target_path = (
            root / item.target_folder / o.sanitize_filename_part(item.shop_name)
            / item.jd_kind / f"{year}年" / f"{month}月（导出时间）"
            / f"{item.download_date}-{item.source.name}"
        )
        item.status = "ready"
        item.reason = "jd_original_archive"


def archive(item, o):
    source, target = item.source, item.target_path
    audit = target.with_name(target.name + ".archive.json")
    if o.file_sha256(source) != item.jd_sha256:
        raise RuntimeError(f"京东源文件在预览后发生变化：{source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with target.open("xb") as output:
            created.append(target)
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, output)
        shutil.copystat(source, target)
        if any(o.file_sha256(path) != item.jd_sha256 for path in (source, target)):
            raise RuntimeError(f"京东原表 SHA256 核对失败：{source.name}")
        with audit.open("x", encoding="utf-8") as output:
            created.append(audit)
            json.dump({
                "platform": "京东", "shop": item.shop_name, "shop_source": item.shop_source,
                "report_type": item.report_type, "archive_category": item.jd_kind,
                "period": item.period, "period_source": item.period_source,
                "source_name": source.name, "archive_name": target.name, "sha256": item.jd_sha256,
                "workbook_encrypted": item.jd_encrypted,
            }, output, ensure_ascii=False, indent=2)
        source.unlink()
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return target
