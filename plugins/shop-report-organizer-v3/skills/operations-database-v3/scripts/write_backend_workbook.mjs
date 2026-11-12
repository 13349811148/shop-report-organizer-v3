import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const moduleRoot=process.env.BACKEND_METRICS_NODE_MODULES;
if(!moduleRoot) throw Error('BACKEND_METRICS_NODE_MODULES is required');
const require=createRequire(path.join(moduleRoot,'package.json'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const data=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const output=process.argv[3];
const workbook=Workbook.create();
function col(n){let result='';for(n++;n;n=Math.floor((n-1)/26))result=String.fromCharCode(65+(n-1)%26)+result;return result;}
function typed(value,header){
  if(header==='排除商品ID')return value;
  if((header==='日期'||header==='适用日期') && /^20\d{2}-\d{2}-\d{2}$/.test(value))return new Date(value+'T00:00:00Z');
  if(/^-?\d+(?:\.\d+)?%$/.test(value))return Number(value.slice(0,-1))/100;
  if(/^-?\d+(?:\.\d+)?(?:星|分)?$/.test(value))return Number(value.replace(/[星分]$/,''));
  // Markdown is evidence. Strings, including formula-like content, stay literal.
  return value.startsWith('=')?"'"+value:value;
}
for(const table of data.tables){
  const sheet=workbook.worksheets.add(table.name);
  sheet.showGridLines=false;
  const derive=table.name==='交易概况';
  const buyerIndex=table.headers.findIndex(h=>['成交买家数','成交买家数（人）'].includes(h));
  const shareIndex=table.headers.findIndex(h=>['老买家占比','成交老买家占比'].includes(h));
  if(derive && (buyerIndex<0 || shareIndex<0))throw Error('计算新老买家数缺少成交买家数或老买家占比');
  const headers=derive?[...table.headers,'新买家数','老买家数']:table.headers;
  const matrix=[headers,...table.rows.map(row=>row.map((v,c)=>typed(v,table.headers[c])).concat(derive?[null,null]:[]))];
  const last=col(headers.length-1);
  const range=sheet.getRange(`A1:${last}${matrix.length}`);
  range.values=matrix;
  range.format.font={name:'Arial',size:11};
  range.format.rowHeight=28;
  range.format.columnWidth=20;
  const header=sheet.getRange(`A1:${last}1`);
  header.format.fill='#176B64';header.format.font={bold:true,color:'#FFFFFF'};
  header.format.wrapText=true;header.format.rowHeight=44;
  if(table.name.startsWith('历史截图转录')){
    sheet.getRange(`${last}1:${last}${matrix.length}`).format.columnWidth=58;
    sheet.getRange(`${last}1:${last}${matrix.length}`).format.wrapText=true;
    sheet.getRange(`A2:${last}${matrix.length}`).format.rowHeight=44;
  }
  for(let c=0;c<table.headers.length;c++){
    const h=table.headers[c];
    const r=sheet.getRange(`${col(c)}2:${col(c)}${matrix.length}`);
    if(h==='日期')r.setNumberFormat('yyyy-mm-dd');
    else if(table.rows.some(row=>row[c].endsWith('%')))r.setNumberFormat('0.00%');
    else if(/星级/.test(h))r.setNumberFormat('0.0"星"');
    else if(h==='服务体验分')r.setNumberFormat('0.0"分"');
    else if(/（元）|成交UV价值/.test(h))r.setNumberFormat('#,##0.00');
    else r.setNumberFormat('#,##0');
  }
  if(['商品排除扣减（估算）','商品排除指标（估算）','待补核对'].includes(table.name)){
    sheet.getRange(`A1:${last}${matrix.length}`).format.wrapText=true;
    sheet.getRange(`A2:${last}${matrix.length}`).format.rowHeight=75;
    sheet.getRange(`C1:C${matrix.length}`).format.columnWidth=48;
    sheet.getRange(`D1:D${matrix.length}`).format.columnWidth=36;
    sheet.getRange(`B1:B${matrix.length}`).format.columnWidth=28;
    sheet.getRange(`B2:B${matrix.length}`).setNumberFormat('0');
    for(let r=0;r<table.rows.length;r++)for(let c=0;c<table.headers.length;c++){
      const raw=table.rows[r][c],cell=sheet.getRange(`${col(c)}${r+2}`);
      if(table.headers[c]==='适用日期')cell.setNumberFormat('yyyy-mm-dd');
      else if(raw.endsWith('%'))cell.setNumberFormat('0.00%');
      else if(/^-?\d+\.\d+$/.test(raw))cell.setNumberFormat('#,##0.00');
      else if(table.headers[c]==='排除商品ID')cell.setNumberFormat('0');
    }
    if(table.name==='商品排除指标（估算）'){
      sheet.getRange(`F1:F${matrix.length}`).format.columnWidth=68;
      sheet.getRange(`A2:${last}${matrix.length}`).format.rowHeight=100;
    }
    if(table.name==='待补核对'){
      sheet.getRange(`E1:F${matrix.length}`).format.columnWidth=65;
      sheet.getRange(`A2:${last}${matrix.length}`).format.rowHeight=120;
    }
  }
  if(derive){
    const total=col(buyerIndex);
    const share=col(shareIndex);
    const newCol=col(table.headers.length),oldCol=col(table.headers.length+1);
    for(let row=2;row<=matrix.length;row++){
      sheet.getRange(`${oldCol}${row}`).formulas=[[`=IF(AND(ISNUMBER(${total}${row}),ISNUMBER(${share}${row}),${total}${row}>=0,${share}${row}>=0,${share}${row}<=1),ROUND(${total}${row}*${share}${row},0),"待补")`]];
      sheet.getRange(`${newCol}${row}`).formulas=[[`=IF(ISNUMBER(${oldCol}${row}),${total}${row}-${oldCol}${row},"待补")`]];
    }
    sheet.getRange(`${newCol}2:${oldCol}${matrix.length}`).setNumberFormat('#,##0');
    // Verify live recalculation, integer rounding, zero and missing inputs; restore source.
    const totalCell=sheet.getRange(`${total}2`),shareCell=sheet.getRange(`${share}2`);
    const originalTotal=totalCell.values,originalShare=shareCell.values;
    totalCell.values=[[10]];shareCell.values=[[0.25]];workbook.recalculate();
    if(sheet.getRange(`${newCol}2:${oldCol}2`).values[0].join(',')!=='7,3')throw Error('买家数公式或取整验证失败');
    totalCell.values=[[0]];workbook.recalculate();
    if(sheet.getRange(`${newCol}2:${oldCol}2`).values[0].join(',')!=='0,0')throw Error('零买家验证失败');
    shareCell.values=[['待补']];workbook.recalculate();
    if(sheet.getRange(`${newCol}2:${oldCol}2`).values[0].join(',')!=='待补,待补')throw Error('缺失占比验证失败');
    totalCell.values=originalTotal;shareCell.values=originalShare;
  }
  sheet.freezePanes.freezeRows(1);
  sheet.tables.add(`A1:${last}${matrix.length}`,true,`Metrics${data.tables.indexOf(table)+1}`);
}
workbook.recalculate();
await fs.mkdir(path.dirname(output),{recursive:true});
for(const name of data.tables.map(t=>t.name)){
  const table=data.tables.find(t=>t.name===name);
  const range=`A1:${col(table.headers.length-1+(name==='交易概况'?2:0))}${Math.min(table.rows.length+1,10)}`;
  const preview=await workbook.render({sheetName:name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(path.dirname(output),name+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(workbook)).save(output);
console.log(JSON.stringify({sheets:data.tables.map(t=>t.name),rowCounts:data.tables.map(t=>t.rows.length),calculations:'新老买家数推算'}));
