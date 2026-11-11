/* CAIUS. / cyber-otaku
   纯原生 JS，无第三方依赖。所有 DOM 操作都做存在性判断，缺元素不报错。 */
(function () {
  'use strict';

  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 1. hero 打字机 ---------- */
  (function typed() {
    var el = $('#hero-typed');
    var lines = window.__HERO_LINES__ || [];
    if (!el || !lines.length) return;
    if (reduceMotion) { el.textContent = lines[0]; return; }

    var li = 0, ci = 0, deleting = false;
    function tick() {
      var line = lines[li];
      el.textContent = line.slice(0, ci);
      if (!deleting) {
        ci++;
        if (ci > line.length) { deleting = true; return setTimeout(tick, 1900); }
      } else {
        ci--;
        if (ci === 0) { deleting = false; li = (li + 1) % lines.length; return setTimeout(tick, 320); }
      }
      setTimeout(tick, deleting ? 32 : 78);
    }
    setTimeout(tick, 500);
  })();

  /* ---------- 2. 代码块 → 终端窗口 ---------- */
  (function codeWindows() {
    var roots = $$('.article-content figure.highlight, .article-content div.highlight, .article-content > pre, .article-content p > pre');
    roots.forEach(function (block) {
      if (block.closest('.code-window')) return;

      // 语言：figure.highlight.java / code.language-java / data-language
      var lang = '';
      var cls = (block.className || '') + ' ' + (block.querySelector('code') ? block.querySelector('code').className : '');
      var m = cls.match(/(?:language|highlight|lang)[-\s]([a-z0-9+#]+)/i) || cls.match(/\b(java|javascript|typescript|python|go|bash|shell|sql|json|yaml|xml|html|css|dockerfile|properties|text)\b/i);
      if (m) lang = m[1].toLowerCase();
      if (!lang && block.tagName === 'FIGURE') {
        var c2 = (block.className || '').match(/highlight\s+([a-z0-9+#]+)/i);
        if (c2) lang = c2[1].toLowerCase();
      }
      var langLabel = { java: 'Java', js: 'JavaScript', javascript: 'JavaScript', ts: 'TypeScript', typescript: 'TypeScript', py: 'Python', python: 'Python', go: 'Go', sh: 'Shell', bash: 'Shell', shell: 'Shell', sql: 'SQL', json: 'JSON', yml: 'YAML', yaml: 'YAML', xml: 'XML', html: 'HTML', css: 'CSS', dockerfile: 'Dockerfile', properties: 'Properties', text: 'TEXT', plain: 'TEXT' }[lang] || (lang ? lang.toUpperCase() : 'CODE');

      var filename = '';
      var cap = block.querySelector('figcaption');
      if (cap) filename = cap.textContent.trim();

      var win = document.createElement('div');
      win.className = 'code-window';
      win.innerHTML =
        '<div class="code-bar">' +
          '<span class="win-dots"><i class="d-red"></i><i class="d-yellow"></i><i class="d-green"></i></span>' +
          '<span class="code-lang">' + langLabel + '</span>' +
          (filename ? '<span class="code-filename">' + filename.replace(/</g, '&lt;') + '</span>' : '') +
          '<button class="code-copy" type="button" aria-label="复制代码">COPY</button>' +
        '</div>';

      block.parentNode.insertBefore(win, block);
      win.appendChild(block);

      var copyBtn = $('.code-copy', win);
      copyBtn.addEventListener('click', function () {
        var pre = $('.code pre', win) || $('pre', win);
        var text = pre ? pre.textContent.replace(/\n{3,}/g, '\n\n').trim() : '';
        var done = function () {
          copyBtn.textContent = 'OK ✓';
          copyBtn.classList.add('copied');
          setTimeout(function () { copyBtn.textContent = 'COPY'; copyBtn.classList.remove('copied'); }, 1600);
        };
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(text).then(done, function () { fallback(text, done); });
        } else { fallback(text, done); }
      });
    });

    function fallback(text, done) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-9999px';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { /* 复制失败不打断页面 */ }
      document.body.removeChild(ta);
    }
  })();

  /* ---------- 3. 站内搜索 ---------- */
  (function search() {
    var overlay = $('#search-overlay'), input = $('#search-input'), results = $('#search-results'), meta = $('#search-meta');
    var trigger = $('#search-trigger');
    if (!overlay || !input || !results) return;

    var index = [], selected = -1, hits = [];

    function load() {
      fetch('/search.json')
        .then(function (r) { if (!r.ok) throw new Error('search.json ' + r.status); return r.json(); })
        .then(function (data) { index = data || []; })
        .catch(function () { index = []; });
    }

    function open() {
      overlay.hidden = false;
      document.body.style.overflow = 'hidden';
      input.focus();
      if (!index.length) load();
    }
    function close() {
      overlay.hidden = true;
      document.body.style.overflow = '';
      input.value = '';
      results.innerHTML = '';
      meta.textContent = '输入至少一个字符开始检索';
      selected = -1;
    }

    function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
    function mark(s, q) {
      var safe = esc(s);
      if (!q) return safe;
      try { return safe.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig'), '<mark>$1</mark>'); }
      catch (e) { return safe; }
    }

    function run(q) {
      q = q.trim().toLowerCase();
      if (!q) { results.innerHTML = ''; meta.textContent = '输入至少一个字符开始检索'; hits = []; return; }
      var terms = q.split(/\s+/);
      hits = index.filter(function (p) {
        var hay = (p.title + ' ' + p.text + ' ' + (p.tags || []).join(' ') + ' ' + (p.categories || []).join(' ')).toLowerCase();
        return terms.every(function (t) { return hay.indexOf(t) > -1; });
      }).slice(0, 30);
      selected = -1;
      meta.textContent = hits.length ? '命中 ' + hits.length + ' 篇 / 索引 ' + index.length + ' 篇' : '没有匹配，换个词试试';
      results.innerHTML = hits.map(function (p, i) {
        var pos = p.text.toLowerCase().indexOf(q);
        var snip = p.text.slice(Math.max(0, pos - 40), pos + 90) || p.text.slice(0, 120);
        return '<li data-i="' + i + '"><a href="' + esc(p.url) + '">' +
          '<span class="sr-date">' + esc(p.date) + ' · ' + esc((p.categories || []).join(' / ')) + '</span>' +
          '<span class="sr-title">' + mark(p.title, q) + '</span>' +
          '<span class="sr-snippet">' + mark(snip, q) + '…</span></a></li>';
      }).join('');
    }

    function move(step) {
      if (!hits.length) return;
      selected = (selected + step + hits.length) % hits.length;
      $$('li', results).forEach(function (li, i) { li.classList.toggle('is-selected', i === selected); });
      var cur = results.children[selected];
      if (cur) cur.scrollIntoView({ block: 'nearest' });
    }

    if (trigger) trigger.addEventListener('click', open);
    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && !/input|textarea/i.test(document.activeElement.tagName) && overlay.hidden) { e.preventDefault(); open(); }
      if (!overlay.hidden) {
        if (e.key === 'Escape') close();
        if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
        if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
        if (e.key === 'Enter' && selected > -1) { window.location.href = hits[selected].url; }
      }
    });
    input.addEventListener('input', function () { run(input.value); });
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
  })();

  /* ---------- 4. 滚动：进度条 / 回顶 / TOC 高亮 ---------- */
  (function scrollUI() {
    var bar = $('#header-progress'), top = $('#back-to-top'), tocLinks = $$('.toc-body .toc a');
    var headings = tocLinks.map(function (a) { return document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1))); }).filter(Boolean);
    var ticking = false;

    function update() {
      var y = window.scrollY || document.documentElement.scrollTop;
      var h = document.documentElement.scrollHeight - window.innerHeight;
      if (bar) bar.style.width = (h > 0 ? (y / h) * 100 : 0) + '%';
      if (top) top.classList.toggle('show', y > 420);
      var active = 0;
      headings.forEach(function (hd, i) { if (hd.getBoundingClientRect().top < 140) active = i; });
      tocLinks.forEach(function (a, i) { a.classList.toggle('is-active', i === active); });
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { window.requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    if (top) top.addEventListener('click', function () { window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' }); });
    update();
  })();

  /* ---------- 5. 移动端菜单 ---------- */
  (function mobileNav() {
    var btn = $('#nav-toggle'), nav = $('#nav');
    if (!btn || !nav) return;
    btn.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      btn.setAttribute('aria-expanded', String(open));
      btn.setAttribute('aria-label', open ? '收起菜单' : '展开菜单');
    });
  })();

  /* ---------- 6. 外链 & 坏图兜底 ---------- */
  (function guards() {
    $$('.article-content a[href^="http"]').forEach(function (a) {
      if (a.hostname !== window.location.hostname) { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener noreferrer'); }
    });
    $$('img').forEach(function (img) {
      img.addEventListener('error', function () {
        // 图挂了不要露出一个裂图图标，换成本站占位
        if (img.dataset.fallback) return;
        img.dataset.fallback = '1';
        img.src = '/images/placeholder.svg';
        img.alt = '图片加载失败';
      });
    });
  })();

  /* ---------- 7. 亮暗主题切换 ---------- */
  (function themeToggle() {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    var icon = document.getElementById('theme-icon');
    var label = document.getElementById('theme-label');
    var meta = document.getElementById('meta-theme-color');
    function sync() {
      var t = document.documentElement.getAttribute('data-theme') || 'dark';
      var light = t === 'light';
      if (icon) icon.textContent = light ? '☀' : '☾';
      if (label) label.textContent = light ? '亮' : '暗';
      if (meta) meta.setAttribute('content', light ? '#f5f7fc' : '#0b0e1a');
    }
    sync();
    btn.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme') || 'dark';
      var next = cur === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
      sync();
    });
    document.addEventListener('keydown', function (e) {
      if ((e.key === 't' || e.key === 'T') && !/^(input|textarea)$/i.test(e.target.tagName || '') && !(e.metaKey || e.ctrlKey || e.altKey)) {
        e.preventDefault();
        btn.click();
      }
    });
  })();
})();
