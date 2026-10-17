// GET /api/news -> { items:[{title, link, source, date}], fetchedAt }，不需要 AI，也不需要 API Key
const QUERY = "(碳費 OR 碳權 OR CBAM OR 永續揭露 OR ESG OR 淨零 OR 綠電 OR 溫室氣體) when:7d";
const FEED = `https://news.google.com/rss/search?q=${encodeURIComponent(QUERY)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant`;
const decode = s => s.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&").trim();
export default async function handler(req, res) {
  try {
    const r = await fetch(FEED, { headers: { "user-agent": "Mozilla/5.0 (sustainability-radar)" } });
    if (!r.ok) throw new Error(`feed ${r.status}`);
    const xml = await r.text();
    const items = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0, 25).map(([, body]) => {
      const get = tag => decode((body.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`)) || [])[1] || "");
      const source = get("source");
      const title = get("title").replace(new RegExp(`\\s*-\\s*${source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`), "");
      const d = new Date(get("pubDate"));
      return { title, link: get("link"), source, date: isNaN(d) ? "" : d.toISOString().slice(0, 10) };
    }).filter(it => it.title && it.link);
    res.setHeader("cache-control", "s-maxage=1800, stale-while-revalidate=3600");
    return res.status(200).json({ items, fetchedAt: new Date().toISOString() });
  } catch (err) { return res.status(502).json({ error: String(err) }); }
}
