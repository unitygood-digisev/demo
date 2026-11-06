// 整個網站需要密碼（HTTP Basic Auth）。密碼放在 Vercel 環境變數 SITE_PASSWORD，帳號欄可填任意文字。
// 沒設定密碼時一律拒絕，不會不小心公開。
export const config = { matcher: '/:path*' };

export default function middleware(request) {
  const password = process.env.SITE_PASSWORD;
  if (!password) {
    return new Response('網站尚未設定密碼，暫不開放。', { status: 503, headers: { 'content-type': 'text/plain; charset=utf-8' } });
  }
  const auth = request.headers.get('authorization') || '';
  if (auth.startsWith('Basic ')) {
    let decoded = '';
    try { decoded = atob(auth.slice(6)); } catch (e) { decoded = ''; }
    const given = decoded.slice(decoded.indexOf(':') + 1);
    if (decoded.includes(':') && given === password) return undefined;
  }
  return new Response('需要密碼才能查看優樂地管理中樞。', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="UnityGood Hub", charset="UTF-8"', 'content-type': 'text/plain; charset=utf-8' },
  });
}
