// GET /api/news -> { items:[{title, link, source, group, date}], anomalies:[{source, error}], fetchedAt }
// 不需要 AI，也不需要 API Key。來源清單與「優樂地管理層系統」config/sources.yaml 的 RSS 來源一致（2026-10-15 版）。
const SOURCES = [
  ["金管會 新聞稿", "法規與準則", "https://www.fsc.gov.tw/RSS/Messages?serno=201202290009&language=chinese"],
  ["金管會 法規草案預告", "法規與準則", "https://www.fsc.gov.tw/RSS/Noticelaw?serno=201202290010&language=chinese"],
  ["金管會 最新法令函釋", "法規與準則", "https://www.fsc.gov.tw/RSS/Newlaw?serno=201202290008&language=chinese"],
  ["金管會 重要公告", "法規與準則", "https://www.fsc.gov.tw/RSS/Messages?serno=201202290001&language=chinese"],
  ["職安署 新聞稿", "法規與準則", "https://www.osha.gov.tw/48110/48417/48419/RssList"],
  ["職安署 公布欄", "法規與準則", "https://www.osha.gov.tw/48110/48417/48423/RssList"],
  ["TNFD 新聞", "法規與準則", "https://tnfd.global/feed/"],
  ["歐盟稅務與關務總署新聞（含 CBAM）", "法規與準則", "https://taxation-customs.ec.europa.eu/node/2/rss_en"],
  ["經濟部能源署 焦點新聞", "法規與準則", "https://www.moeaea.gov.tw/ECW/populace/news/NewsRSSdetail.aspx?Kind=1"],
  ["勞動部 新聞稿", "法規與準則", "https://www.mol.gov.tw/1607/1632/1633/RssList"],
  ["勞動部 公布欄", "法規與準則", "https://www.mol.gov.tw/1607/1632/2665/RssList"],
  ["衛生福利部 焦點新聞", "法規與準則", "https://www.mohw.gov.tw/rss-16-1.html"],
  ["衛生福利部 公告訊息", "法規與準則", "https://www.mohw.gov.tw/rss-18-1.html"],
  ["經濟部產業發展署 新聞發布", "法規與準則", "https://www.ida.gov.tw/ctlr?PRO=rss.RSSView&t=1"],
  ["經濟部產業發展署 法令規章", "法規與準則", "https://www.ida.gov.tw/ctlr?PRO=rss.RSSView&t=2"],
  ["Carbon Brief", "法規與準則", "https://www.carbonbrief.org/feed/"],
  ["Climate Home News", "法規與準則", "https://www.climatechangenews.com/feed/"],
  ["GSTC 全球永續旅遊委員會", "法規與準則", "https://www.gstc.org/feed/"],
  ["歐盟執委會 氣候行動新聞", "法規與準則", "https://climate.ec.europa.eu/node/2/rss_en"],
  ["台灣永續能源研究基金會 TAISE", "同業動態", "https://taise.org.tw/feed/"],
  ["ESG遠見", "同業動態", "https://esg.gvm.com.tw/feed"],
  ["ESG Today", "同業動態", "https://www.esgtoday.com/feed/"],
  ["Trellis（原 GreenBiz）", "同業動態", "https://trellis.net/feed/"],
  ["Social Value International", "同業動態", "https://www.socialvalueint.org/blog?format=rss"],
  ["edie", "同業動態", "https://www.edie.net/feed/"],
  ["中央社 財經", "客戶動態", "https://feeds.feedburner.com/rsscna/finance"],
  ["中央社 科技", "客戶動態", "https://feeds.feedburner.com/rsscna/technology"],
  ["自由時報 財經", "客戶動態", "https://news.ltn.com.tw/rss/business.xml"],
  ["鉅亨網", "客戶動態", "https://news.cnyes.com/rss/v1/news/category/all"],
  ["ETtoday 財經", "客戶動態", "https://feeds.feedburner.com/ettoday/finance"],
  ["科技新報", "客戶動態", "https://technews.tw/feed/"],
  ["科技新報 財經", "客戶動態", "https://finance.technews.tw/feed/"],
  ["遠見雜誌", "客戶動態", "https://www.gvm.com.tw/rss"],
  ["中央社 生活醫藥", "其他", "https://feeds.feedburner.com/rsscna/lifehealth"],
  ["自由時報 生活", "其他", "https://news.ltn.com.tw/rss/life.xml"],
  ["報導者", "其他", "https://www.twreporter.org/a/rss2.xml"],
];
const DAYS = 7, PER_SOURCE = 40, TIMEOUT_MS = 8000;
const decode = s => s.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n)).replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
function parse(xml) {
  const blocks = [...xml.matchAll(/<(item|entry)[\s>]([\s\S]*?)<\/\1>/g)].map(m => m[2]);
  return blocks.map(body => {
    const get = tag => decode((body.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`)) || [])[1] || "");
    const link = get("link") || (body.match(/<link[^>]*href="([^"]+)"/) || [])[1] || "";
    const d = new Date(get("pubDate") || get("published") || get("updated") || get("dc:date"));
    return { title: get("title"), link: link.trim(), excerpt: get("description") || get("summary"), date: isNaN(d) ? null : d };
  }).filter(it => it.title && /^https?:\/\//.test(it.link));
}
async function fetchSource([name, group, url], since) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(url, { signal: ctl.signal, headers: { "user-agent": "Mozilla/5.0 (sustainability-radar; unitygood intel)" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const items = parse(await r.text());
    if (!items.length) throw new Error("讀不到任何文章（格式不符）");
    return items.filter(it => !it.date || it.date >= since).slice(0, PER_SOURCE).map(it => ({
      title: it.title, link: it.link, excerpt: it.excerpt.slice(0, 300), source: name, group,
      date: it.date ? it.date.toISOString().slice(0, 10) : "",
    }));
  } catch (err) {
    throw { source: name, error: err.name === "AbortError" ? "連線逾時" : String(err.message || err) };
  } finally { clearTimeout(t); }
}
export default async function handler(req, res) {
  const since = new Date(Date.now() - DAYS * 86400000);
  const results = await Promise.allSettled(SOURCES.map(s => fetchSource(s, since)));
  const seen = new Set(), items = [], anomalies = [];
  results.forEach(r => {
    if (r.status === "rejected") return anomalies.push(r.reason);
    r.value.forEach(it => { const k = it.link.replace(/[?#].*$/, ""); if (!seen.has(k)) { seen.add(k); items.push(it); } });
  });
  items.sort((a, b) => b.date.localeCompare(a.date));
  res.setHeader("cache-control", "s-maxage=1800, stale-while-revalidate=3600");
  return res.status(200).json({ items, anomalies, sources: SOURCES.length, fetchedAt: new Date().toISOString() });
}
