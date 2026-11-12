import tempfile,unittest
from pathlib import Path
import backend_markdown as m
class Tests(unittest.TestCase):
    def parse(self,body):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.md';p.write_text(body,encoding='utf-8');return m.parse(p)
    def sample(self,rows='|2026-10-23|0|待补|'):
        return '店铺：甲旗舰店。日期：2026-10-23\n\n|日期|成交金额（元）|订单数|\n|---|---:|---:|\n'+rows+'\n\n来源：用户确认；不得当作页面实测。'
    def test_zero_and_missing_stay_distinct(self):
        d=self.parse(self.sample());self.assertEqual(d['tables'][0]['rows'][0][1:],['0','待补']);self.assertIn('用户确认',''.join(d['notes']))
    def test_duplicate_dates_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.sample('|2026-10-23|1|1|\n|2026-10-23|2|2|'))
    def test_unknown_table_rejected_without_loss(self):
        with self.assertRaises(ValueError):self.parse(self.sample()+'\n|日期|不认识|\n|---|---|\n|2026-10-23|2|')
    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.sample('|2026-02-30|1|2|'))
    def test_bad_columns_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.sample('|2026-10-23|1|'))
    def test_missing_shop_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.sample().replace('店铺：甲旗舰店。',''))
    def test_short_date_and_display_numbers(self):
        body='- 店铺：甲旗舰店\n- 统计日期：2026-10-30（北京时间）\n|日期|成交金额（元）|成交买家数（人）|成交老买家占比|\n|---|---|---|---|\n|10-30|4,530.32|181|31.50%|\n\n|日期|综合体验星级|服务体验分|\n|---|---|---|\n|10-30|5 星|3.6 分|'
        d=self.parse(body)
        self.assertEqual(d['shop'],'甲旗舰店')
        self.assertEqual(d['tables'][0]['rows'][0],['2026-10-30','4530.32','181','31.50%'])
        self.assertEqual(d['tables'][1]['rows'][0],['2026-10-30','5星','3.6分'])
    def test_short_date_without_reporting_year_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.sample('|10-23|1|2|'))
    def test_short_date_conflicting_year_rejected(self):
        with self.assertRaises(ValueError):self.parse('统计日期：2025-10-23\n统计日期：2026-10-23\n'+self.sample('|10-23|1|2|'))
    def test_short_date_must_match_reporting_date(self):
        with self.assertRaises(ValueError):self.parse('统计日期：2026-10-24\n'+self.sample('|10-23|1|2|'))
    def test_historical_transcript_separate_from_reporting_period(self):
        body=self.sample()+'\n## 日期不匹配的历史截图数据（不计入本周）\n\n|日期|成交金额（元）|成交买家数（人）|\n|---|---|---|\n|2026-10-03|1,966.92|122|\n'
        d=self.parse(body)
        self.assertEqual((d['start'],d['end']),('2026-10-23','2026-10-23'))
        self.assertEqual(d['tables'][1]['name'],'历史截图转录（交易）')
        self.assertEqual(d['tables'][1]['rows'][0][:3],['2026-10-03','1966.92','122'])
        self.assertIn('不计入本周',d['tables'][1]['rows'][0][-1])
    def test_duplicate_main_table_still_rejected(self):
        with self.assertRaises(ValueError):self.parse(self.sample()+'\n|日期|成交金额（元）|\n|---|---|\n|2026-10-03|1|')
    def test_historical_section_ends_at_next_heading(self):
        body=self.sample()+'\n## 日期不匹配的历史截图数据（不计入本周）\n\n|日期|成交金额（元）|\n|---|---|\n|2026-10-03|1|\n\n## 其他\n\n|日期|成交金额（元）|\n|---|---|\n|2026-10-04|2|'
        with self.assertRaises(ValueError):self.parse(body)
    def test_exact_shop_identity_and_snapshot_path(self):
        d=self.parse(self.sample());p=m.target_for(Path('db'),d);self.assertIn('甲旗舰店',p.parts);self.assertIn(d['sha256'][:12],p.name)
    def test_dry_run_keeps_input(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'source.md';p.write_text(self.sample(),encoding='utf-8')
            self.assertEqual(m.process(root,root,False),0);self.assertTrue(p.exists());self.assertFalse(list(root.rglob('*.xlsx')))
    def test_traffic_values_and_labels_preserved(self):
        d=self.parse('店铺：甲旗舰店。\n|日期|店铺访客数（人）|店铺浏览量（次）|商品访客数（人）|商品浏览量（次）|成交UV价值（页面原值）|\n|---|---:|---:|---:|---:|---:|\n|2026-10-23|0|2188|1358|1989|0.73|\n')
        table=d['tables'][0]
        self.assertEqual(table['name'],'流量数据')
        self.assertEqual(table['rows'][0][1],'0')
        self.assertEqual(table['rows'][0][-1],'0.73')
        self.assertEqual(table['headers'][-1],'成交UV价值（页面原值）')
    def test_traffic_missing_not_zero(self):
        d=self.parse('店铺：甲旗舰店。\n|日期|店铺访客数（人）|成交UV价值（页面原值）|\n|---|---:|---:|\n|2026-10-23|待补|待补|\n')
        self.assertEqual(d['tables'][0]['rows'][0][1:],['待补','待补'])

    def analysis_sample(self,scope=True):
        body='店铺：甲旗舰店。\n商品ID **1021621380194**。'+('只排除2026年10月27日。' if scope else '')+'\n'
        body+='|日期|成交金额（元）|成交买家数（人）|成交老买家占比|\n|---|---:|---:|---:|\n|2026-10-27|4085.89|153|20.92%|\n'
        body+='\n|指标|店铺/商品汇总原值|排除商品值|直接扣减后|\n|---|---:|---:|---:|\n|成交金额（元）|4085.89|997.20|3088.69|\n'
        return body
    def test_analysis_separate_from_original(self):
        d=self.parse(self.analysis_sample());tables={t['name']:t for t in d['tables']}
        self.assertEqual(tables['交易概况']['rows'][0][1],'4085.89')
        adjusted=tables['商品排除扣减（估算）']['rows'][0]
        self.assertEqual(adjusted[:2],['2026-10-27','1021621380194'])
        self.assertIn('非平台实测',adjusted[2]);self.assertEqual(adjusted[-1],'3088.69')
    def test_analysis_requires_explicit_scope(self):
        with self.assertRaises(ValueError):self.parse(self.analysis_sample(False))
    def test_analysis_date_outside_original_rejected(self):
        body=self.analysis_sample().replace('只排除2026年10月27日','只排除2026年10月26日')
        with self.assertRaises(ValueError):self.parse(body)

if __name__=='__main__':unittest.main()
