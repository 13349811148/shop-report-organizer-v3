"""Archive original PDD promotion exports without business calculations."""
from pathlib import Path
import hashlib
import os
import shutil
import tempfile


def classify(rows, o):
    for index, headers in enumerate(rows[:20]):
        spend = o.find_header_index(headers, ['总花费(元)', '成交花费(元)', '成交花费(元)（分摊）'])
        date = o.find_header_index(headers, ['日期','统计日期','推广日期','业务日期','统计时间'])
        if spend is None or date is None:
            continue
        # Do not mistake sales/order tables for a promotion export.
        if not any(o.find_header_index(headers,[h]) is not None for h in ['曝光量','点击量','推广名称','推广场景','净实际投产比','实际投产比','成交花费(元)（分摊）']):
            continue
        pid = o.find_header_index(headers,['商品ID','商品id','主体ID'])
        scene = o.find_header_index(headers,['推广场景','推广类型','推广方式'])
        kinds=set(); dates=set(); ids=set()
        for row in rows[index+1:]:
            if date < len(row):
                parsed=o.parse_date(row[date])
                if parsed: dates.add(parsed.isoformat())
            if pid is not None and pid < len(row):
                value=o.normalize_product_id(row[pid])
                if value: ids.add(value)
            if scene is not None and scene < len(row):
                value=o.normalize_text(row[scene])
                if value in {'全店托管','商品推广'}: kinds.add(value)
        if kinds == {'全店托管'}:
            kind='全店托管'
        elif kinds == {'商品推广'}:
            kind='商品推广'
        elif len(kinds)>1:
            kind='混合推广原表'
        elif pid is None:
            kind='账户每日汇总'
        elif o.find_header_index(headers,['成交花费(元)（分摊）']) is not None:
            kind='全店托管'
        else:
            kind='推广类型待确认'
        period=f'{min(dates)}至{max(dates)}' if dates else ''
        return kind,period,sorted(ids),headers
    return None


def analyze(source,rows,database_root,product_map,shops,o):
    detected=classify(rows,o)
    if detected is None: return None
    kind,period,ids,headers=detected
    shop,shop_source,counts=o.decide_shop(source,'推广数据',rows,ids,product_map,shops)
    mapped_shops={product_map[v] for v in ids if v in product_map}
    if len(mapped_shops)>1:
        shop=''; shop_source='conflicting_product_id_map'
    elif not shop:
        filename_shop,filename_source=o.extract_shop_from_filename(source,shops)
        if filename_shop and filename_shop not in {'拼多多','天猫','淘宝','pdd','tmall'}:
            shop,shop_source=filename_shop,filename_source
    missing=[]
    if not shop: missing.append('shop_name')
    if not period: missing.append('period')
    a=o.Analysis(source=source,status='pending' if missing else 'ready',
        reason='missing_required_fields' if missing else 'promotion_archive_only',
        report_type='推广数据',target_folder=o.PROMOTION_DATABASE_DIR,shop_name=shop,
        shop_source=shop_source,period=period,period_source='date_column',
        download_date=o.download_date(source).isoformat(),target_path=source,
        product_counts=counts,matched_headers='|'.join(h for h in headers if h),
        missing_fields=';'.join(missing),map_updates=[],product_ids=ids,
        new_product_ids=[v for v in ids if v not in product_map],raw_promotion_kind=kind)
    finalize(a,database_root,o)
    return a


def finalize(a,database_root,o):
    if not a.raw_promotion_kind or a.status not in {'ready','pending'}: return
    if not a.shop_name or not a.period: return
    a.status='ready'; a.reason='promotion_archive_only'; a.missing_fields=''
    date=a.download_date
    a.target_path=(database_root/o.PROMOTION_DATABASE_DIR/o.sanitize_filename_part(a.shop_name)/
        a.raw_promotion_kind/(date[:4]+'年')/(date[5:7]+'月（导出时间）')/
        (date+'-'+a.source.name))


def archive(a,o):
    if a.status!='ready' or not a.raw_promotion_kind:
        raise RuntimeError('推广归档计划未通过检查，保留源文件')
    target=o.unique_path(a.target_path)
    target.parent.mkdir(parents=True,exist_ok=True)
    source_hash=o.file_sha256(a.source)
    fd,tmp=tempfile.mkstemp(prefix='.archive-',suffix=target.suffix,dir=target.parent)
    os.close(fd); tmp=Path(tmp)
    try:
        shutil.copy2(a.source,tmp)
        if o.file_sha256(tmp)!=source_hash:
            raise RuntimeError('推广原始文件SHA256核对失败，保留源文件')
        # Check once more before installation; no overwriting an existing archive.
        if target.exists(): target=o.unique_path(target)
        os.replace(tmp,target)
        if o.file_sha256(a.source)!=source_hash:
            target.unlink()
            raise RuntimeError('归档期间源文件发生改变，保留源文件')
        a.source.unlink()
    finally:
        if tmp.exists(): tmp.unlink()
    a.target_path=target
    audit=target.with_name(target.name+'.archive.json')
    import json
    audit.write_text(json.dumps({'source_name':a.source.name,'archive_name':target.name,
        'sha256':source_hash,'shop':a.shop_name,'promotion_category':a.raw_promotion_kind,
        'period':a.period,'business_calculations':False,
        'note':'原始文件按字节归档，未分摊花费、未计算ROI或每笔成交花费；这些计算由日报Skill处理。'},ensure_ascii=False,indent=2),encoding='utf-8')
    return target
