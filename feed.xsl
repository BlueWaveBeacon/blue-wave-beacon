<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" encoding="UTF-8" indent="yes"/>
  <xsl:template match="/rss/channel">
    <html lang="en">
      <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title><xsl:value-of select="title"/> — RSS Feed</title>
        <style>
          :root { --navy:#0d2247; --blue:#1a56db; }
          * { box-sizing:border-box; }
          body { margin:0; background:#f1f5f9; color:#0f172a;
                 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
                 line-height:1.5; }
          .wrap { max-width:760px; margin:0 auto; padding:24px 18px 56px; }
          header { background:linear-gradient(135deg,var(--navy),var(--blue)); color:#fff;
                   border-radius:10px; padding:24px 22px; }
          header h1 { margin:0 0 6px; font-size:24px; letter-spacing:1px; }
          header p { margin:0; opacity:.9; font-size:15px; }
          .note { background:#e0ecff; border:1px solid #b9d2ff; color:#13347a;
                  border-radius:8px; padding:12px 14px; font-size:13.5px; margin:18px 0 24px; }
          .note a { color:var(--blue); font-weight:600; }
          .count { font-size:13px; color:#64748b; margin:0 0 10px; text-transform:uppercase; letter-spacing:1px; }
          article { background:#fff; border:1px solid #e2e8f0; border-radius:8px;
                    padding:14px 16px; margin-bottom:10px; }
          article a.title { color:var(--navy); font-weight:600; font-size:16px;
                            text-decoration:none; }
          article a.title:hover { color:var(--blue); text-decoration:underline; }
          .meta { margin-top:6px; font-size:12.5px; color:#64748b; }
          .meta .src { color:var(--blue); font-weight:600; }
          footer { text-align:center; margin-top:28px; font-size:13px; color:#64748b; }
          footer a { color:var(--blue); }
        </style>
      </head>
      <body>
        <div class="wrap">
          <header>
            <h1>🌊 <xsl:value-of select="title"/></h1>
            <p><xsl:value-of select="description"/></p>
          </header>

          <div class="note">
            📡 This is an <strong>RSS feed</strong> — a live list of our latest headlines.
            To follow it, copy this page's web address into a feed reader app (like
            Feedly or Inoreader). Or just visit
            <a href="https://bluewavebeacon.com/">bluewavebeacon.com</a> any time.
          </div>

          <p class="count"><xsl:value-of select="count(item)"/> latest headlines</p>

          <xsl:for-each select="item">
            <article>
              <a class="title" href="{link}" target="_blank" rel="noopener noreferrer">
                <xsl:value-of select="title"/>
              </a>
              <div class="meta">
                <span class="src"><xsl:value-of select="source"/></span>
                <xsl:text> &#183; </xsl:text>
                <xsl:value-of select="pubDate"/>
              </div>
            </article>
          </xsl:for-each>

          <footer>
            &#169; BLUE WAVE BEACON ·
            <a href="https://bluewavebeacon.com/">Home</a>
          </footer>
        </div>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
