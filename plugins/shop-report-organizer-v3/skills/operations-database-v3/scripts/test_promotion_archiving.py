"""Promotion archive-only behavior: missing metrics and all bytes survive."""
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import organize_reports as o
import promotion_archiving as arch

class ArchiveTests(unittest.TestCase):
    def source(self,root,name,rows):
        p=root/name
        with p.open('w',encoding='utf-8-sig',newline='') as f: csv.writer(f).writerows(rows)
        return p
    def analyze(self,p,root,mapping=None):
        return o.analyze_file(p,root,o.load_signatures(),mapping or {},[],100000,120)
    def test_managed_missing_cost_and_roi_preserved_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=self.source(root,'报表（测试旗舰店）.csv',[
                ['日期','商品ID','推广场景','交易额(元)','总花费(元)','实际投产比'],
                ['2026-10-22','123456789012','全店托管','200','-','-'],
                ['2026-10-21','123456789013','全店托管','0','','n.a.']])
            before=p.read_bytes(); a=self.analyze(p,root)
            self.assertEqual((a.status,a.raw_promotion_kind),('ready','全店托管'))
            o.validate_promotion_merge_inputs([a],120)
            with patch.object(o,'merge_promotion_data',side_effect=AssertionError('must not calculate/merge')):
                o.apply_actions([a],root,False,{},root/'map.csv',100000,120)
            self.assertFalse(p.exists());self.assertEqual(a.target_path.read_bytes(),before)
            self.assertIn('全店托管',a.target_path.parts)
            self.assertTrue(a.target_path.with_name(a.target_path.name+'.archive.json').exists())
    def test_account_summary_without_product_id_is_archiveable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.source(root,'账户（测试旗舰店）.csv',[
                ['日期','总花费(元)','点击量'],['2026-10-22','1000','90']])
            a=self.analyze(p,root)
            self.assertEqual(a.status,'ready');self.assertEqual(a.product_ids,[])
            self.assertEqual(a.raw_promotion_kind,'账户每日汇总')
    def test_product_and_managed_same_id_stay_separate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);header=['日期','商品ID','推广场景','总花费(元)','点击量']
            analyses=[]
            for scene in ['全店托管','商品推广']:
                p=self.source(root,scene+'（测试旗舰店）.csv',[header,['2026-10-22','123456789012',scene,'10','1']])
                a=self.analyze(p,root);analyses.append(a); arch.archive(a,o)
            self.assertNotEqual(analyses[0].target_path.parent,analyses[1].target_path.parent)
    def test_conflicting_or_unknown_shop_does_not_auto_archive(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.source(root,'报表.csv',[
                ['日期','商品ID','推广场景','总花费(元)','点击量'],['2026-10-22','123456789012','全店托管','-','1']])
            a=self.analyze(p,root);self.assertEqual(a.status,'pending');self.assertTrue(p.exists())
    def test_existing_filename_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.source(root,'报表（测试旗舰店）.csv',[
                ['日期','推广场景','总花费(元)','点击量'],['2026-10-22','全店托管','-','1']])
            a=self.analyze(p,root);a.target_path.parent.mkdir(parents=True)
            a.target_path.write_bytes(b'previous snapshot');old=a.target_path
            arch.archive(a,o);self.assertEqual(old.read_bytes(),b'previous snapshot')
            self.assertNotEqual(old,a.target_path)
    def test_multi_shop_map_stays_pending_after_batch_inference(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.source(root,'报表.csv',[
                ['日期','商品ID','推广场景','总花费(元)','点击量'],
                ['2026-10-22','123456789012','全店托管','-','1'],
                ['2026-10-22','123456789013','全店托管','-','1']])
            a=self.analyze(p,root,{'123456789012':'甲店','123456789013':'乙店'})
            o.apply_batch_shop_inference(root,[a],o.load_signatures(),{})
            arch.finalize(a,root,o)
            self.assertEqual(a.status,'pending')
            with self.assertRaises(RuntimeError): arch.archive(a,o)
    def test_no_id_account_can_use_single_shop_batch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            account=self.source(root,'汇总.csv',[['日期','总花费(元)','点击量'],['2026-10-22','10','1']])
            detail=self.source(root,'明细（测试旗舰店）.csv',[
                ['日期','商品ID','推广场景','总花费(元)','点击量'],['2026-10-22','123456789012','商品推广','3','1']])
            a,b=self.analyze(account,root),self.analyze(detail,root)
            o.apply_batch_shop_inference(root,[a,b],o.load_signatures(),{})
            self.assertEqual((a.status,a.shop_name),('ready','测试旗舰店'))
    def test_order_export_not_mistaken_for_promotion(self):
        self.assertIsNone(arch.classify([['订单号','支付时间','商品ID','实付金额'],['1','2026-10-22','123456789012','10']],o))

if __name__=='__main__': unittest.main()
