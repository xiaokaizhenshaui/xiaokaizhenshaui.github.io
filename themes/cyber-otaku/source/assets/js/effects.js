/* ============================================================
   CAIUS. / Night City FX
   纯原生 JS。依赖顺序：agent-build.min.js → effects.js → main.js
   所有开关存 localStorage，任何一步拿不到 DOM 都静默跳过。
   ============================================================ */
(function () {
  'use strict';

  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root  = document.documentElement;
  var layer = $('#fx-layer');
  if (!layer) return;                       // 主题里关掉了特效
  if (!window.matchMedia) return;

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  var STORE = 'cerulean-fx-v2';
  var defaults = { particles: true, city: true, scan: true, glow: true, waifu: true };
  var state = {};
  Object.keys(defaults).forEach(function (k) { state[k] = defaults[k]; });
  try {
    var saved = JSON.parse(localStorage.getItem(STORE) || '{}');
    Object.keys(defaults).forEach(function (k) { if (typeof saved[k] === 'boolean') state[k] = saved[k]; });
  } catch (e) { /* 隐私模式下 localStorage 可能抛异常 */ }

  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* 忽略 */ }
  }

  /* ---------- HUD ---------- */
  var hud = $('.fx-hud'), hudState = $('#fx-state'), clock = $('#fx-clock');
  function setHud(text, busy) {
    if (hudState) hudState.textContent = text;
    if (hud) hud.classList.toggle('is-busy', !!busy);
  }
  function pad(n) { return n < 10 ? '0' + n : String(n); }
  function tickClock() {
    if (!clock) return;
    var d = new Date();
    clock.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  tickClock();
  setInterval(tickClock, 1000);

  /* ---------- 1. agent-build：中文本地化 + 事件联动 ---------- */
  var AB = window.AgentBuild;
  var buildBtn = $('[data-agent-build]');

  if (AB && typeof AB.addLocale === 'function') {
    // 库要求 label/started/finished 以 kicker 开头、built 含 kicker，
    // 且始终标明这是一场模拟，不能把访客骗成真在加载。
    try {
      AB.addLocale('zh-CN', {
        kicker: 'SIMULATION',
        label: 'SIMULATION · 让 agent 把页面重搭一遍',
        cta: '看它怎么盖起来',
        agents: { one: '{count} 个 agent', other: '{count} 个 agent' },
        layers: '{done}/{total} 层',
        pause: '暂停',
        resume: '继续',
        finish: '结束',
        started: 'SIMULATION 运行中：一群 agent 正在逐块重建页面，按 Esc 结束。',
        built: '{seconds} 秒搭完 · 这是一场 SIMULATION',
        finished: 'SIMULATION 结束，页面已完整。'
      });
    } catch (e) {
      console.warn('[fx] agent-build 中文文案注册失败:', e.message);
    }
  }

  function rebuild() {
    if (!AB || typeof AB.start !== 'function') return;
    AB.start({ trigger: buildBtn || undefined });
  }

  document.addEventListener('agentbuild:start', function () {
    document.body.classList.add('agent-running');
    setHud('REBUILDING', true);
    stopParticles();
  });
  document.addEventListener('agentbuild:end', function () {
    document.body.classList.remove('agent-running');
    setHud('ONLINE', false);
    if (state.particles && !reduce && !document.hidden) startParticles();
  });

  // 首页 hero 里的入口：库不可用时这个按钮保持隐藏
  var heroBtn = $('#fx-rebuild-trigger');
  if (heroBtn && AB) {
    heroBtn.hidden = false;
    heroBtn.addEventListener('click', rebuild);
  }

  // 彩蛋：Konami code 或 Ctrl/⌘ + Shift + B
  var konami = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
  var kpos = 0;
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && String(e.key).toLowerCase() === 'b') {
      e.preventDefault(); rebuild(); return;
    }
    if (/input|textarea|select/i.test((e.target && e.target.tagName) || '')) return;
    var key = String(e.key).length === 1 ? e.key.toLowerCase() : e.key;
    kpos = (key === konami[kpos]) ? kpos + 1 : (key === konami[0] ? 1 : 0);
    if (kpos === konami.length) { kpos = 0; rebuild(); }
  });

  /* ---------- 2. 霓虹粒子 / 数据流 ---------- */
  var canvas = $('#fx-particles');
  var ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
  var parts = [], raf = 0, W = 0, H = 0, dpr = 1, running = false;
  var mx = -999, my = -999;
  var palette = ['69,224,245', '255,119,200', '169,139,255', '156,232,132'];

  function resizeParticles() {
    if (!canvas || !ctx) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function seedParticles() {
    if (!canvas || !ctx) return;
    var n = Math.min(parseInt(layer.getAttribute('data-particles') || '60', 10) || 60, 110);
    if (W < 720) n = Math.round(n * 0.5);
    parts = [];
    for (var i = 0; i < n; i++) {
      parts.push({
        x: Math.random() * W,
        y: Math.random() * H,
        r: 0.7 + Math.random() * 1.6,
        vx: (Math.random() - 0.5) * 0.22,
        vy: -0.06 - Math.random() * 0.24,
        a: 0.18 + Math.random() * 0.32,
        c: palette[Math.floor(Math.random() * palette.length)]
      });
    }
  }

  function drawParticles() {
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);

    var i, p;
    for (i = 0; i < parts.length; i++) {
      p = parts[i];
      // 鼠标附近轻微推开，像被光标扰动的数据流
      var dx = p.x - mx, dy = p.y - my;
      var d2 = dx * dx + dy * dy;
      if (d2 < 16000 && d2 > 1) {
        var f = (16000 - d2) / 16000 * 0.5;
        var d = Math.sqrt(d2);
        p.x += dx / d * f; p.y += dy / d * f;
      }
      p.x += p.vx; p.y += p.vy;
      if (p.y < -8) { p.y = H + 8; p.x = Math.random() * W; }
      if (p.x < -8) p.x = W + 8;
      if (p.x > W + 8) p.x = -8;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + p.c + ',' + p.a + ')';
      ctx.fill();
    }

    // 只对前 26 个粒子连线，避免 O(n²) 拖慢长文页面
    var lim = Math.min(parts.length, 26);
    for (i = 0; i < lim; i++) {
      for (var j = i + 1; j < lim; j++) {
        var a = parts[i], b = parts[j];
        var dd = (a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y);
        if (dd < 13000) {
          ctx.beginPath();
          ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
          ctx.strokeStyle = 'rgba(69,224,245,' + (0.055 * (1 - dd / 13000)) + ')';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    }
    raf = window.requestAnimationFrame(drawParticles);
  }

  function startParticles() {
    if (!ctx || running || reduce || document.hidden) return;
    resizeParticles();
    if (!parts.length) seedParticles();
    running = true;
    raf = window.requestAnimationFrame(drawParticles);
  }
  function stopParticles() {
    running = false;
    if (raf) window.cancelAnimationFrame(raf);
    raf = 0;
    if (ctx) ctx.clearRect(0, 0, W, H);
  }
  window.addEventListener('resize', function () {
    if (!running) return;
    resizeParticles();
    seedParticles();
  }, { passive: true });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stopParticles();
    else if (state.particles && !reduce && !document.body.classList.contains('agent-running')) startParticles();
  });

  /* ---------- 3. 鼠标光晕 ---------- */
  var glow = $('#fx-cursor-glow');
  var glowTick = false;
  document.addEventListener('mousemove', function (e) {
    mx = e.clientX; my = e.clientY;
    if (!glow || glowTick || !state.glow || reduce || !finePointer) return;
    glowTick = true;
    window.requestAnimationFrame(function () {
      root.style.setProperty('--fx-mx', mx + 'px');
      root.style.setProperty('--fx-my', my + 'px');
      glow.classList.add('is-on');
      glowTick = false;
    });
  }, { passive: true });

  /* ---------- 4. glitch 文字 ---------- */
  var glitchables = $$('[data-glitch]');
  function pulse(el) {
    if (!el || reduce) return;
    el.classList.remove('is-glitching');
    // 强制重排，连点两次也能重新播放
    void el.offsetWidth;
    el.classList.add('is-glitching');
    setTimeout(function () { el.classList.remove('is-glitching'); }, 820);
  }
  glitchables.forEach(function (el) {
    el.addEventListener('mouseenter', function () { pulse(el); });
  });
  function scheduleGlitch() {
    setTimeout(function () {
      if (!reduce && !document.hidden && glitchables.length) {
        pulse(glitchables[Math.floor(Math.random() * glitchables.length)]);
      }
      scheduleGlitch();
    }, 7000 + Math.random() * 9000);
  }
  if (!reduce) scheduleGlitch();

  /* ---------- 5. 滚动进场 ---------- */
  if (!reduce && 'IntersectionObserver' in window) {
    var targets = $$('.series-card, .archive-year, .panel, .article-content > h2');
    targets.forEach(function (el) { el.classList.add('fx-reveal', 'is-ready'); });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add('is-in');
        io.unobserve(en.target);
        // 动画结束后把类摘干净，别覆盖卡片原有的 hover transform
        setTimeout(function () {
          en.target.classList.remove('fx-reveal', 'is-ready', 'is-in');
        }, 700);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
    targets.forEach(function (el) { io.observe(el); });
  }

  /* ---------- 6. 卡片 3D 倾斜 ---------- */
  if (!reduce && finePointer) {
    $$('.post-card, .series-card').forEach(function (card) {
      card.addEventListener('mousemove', function (e) {
        var r = card.getBoundingClientRect();
        var px = (e.clientX - r.left) / r.width - 0.5;
        var py = (e.clientY - r.top) / r.height - 0.5;
        card.style.setProperty('--fx-rx', (-py * 5).toFixed(2) + 'deg');
        card.style.setProperty('--fx-ry', (px * 6).toFixed(2) + 'deg');
        card.setAttribute('data-fx-tilt', '');
      });
      card.addEventListener('mouseleave', function () {
        card.removeAttribute('data-fx-tilt');
        card.style.removeProperty('--fx-rx');
        card.style.removeProperty('--fx-ry');
      });
    });
  }

  /* ---------- 7. 看板娘台词 ---------- */
  var bubble = $('#fx-waifu-bubble'), face = $('#fx-waifu-face');
  var bubbleTimer = 0;
  var lines = [
    '又是没写测试的一天 (｀・ω・´)',
    '生产环境别乱动，我看着呢。',
    '缓存又穿透了？先别急着重启。',
    '今天也别把生产搞挂了 ≧▽≦',
    'commit 之前，先跑一遍 build。',
    '夜不下班，你也别下得太晚。',
    '索引没生效的时候，先看看 explain。',
    '这段日志我帮你看过了，是凌晨三点的。',
    '代码能跑 ≠ 代码没问题，懂吧。'
  ];
  var greeting = '站修好了，图也换新的了。慢慢翻。';
  function say(text) {
    if (!bubble || !text) return;
    bubble.textContent = text;
    bubble.classList.add('is-on');
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(function () { bubble.classList.remove('is-on'); }, 5200);
  }
  if (face) {
    face.addEventListener('click', function () { say(lines[Math.floor(Math.random() * lines.length)]); });
    setTimeout(function () {
      var seen = false;
      try { seen = sessionStorage.getItem('fx-greeted') === '1'; } catch (e) { /* 忽略 */ }
      if (!seen && state.waifu && !reduce) {
        say(greeting);
        try { sessionStorage.setItem('fx-greeted', '1'); } catch (e) { /* 忽略 */ }
      }
    }, 4200);
  }

  /* ---------- 8. 特效控制台 ---------- */
  function apply(key, on) {
    state[key] = !!on;
    document.body.classList.toggle('fx-' + key + '-off', !on);
    if (key === 'particles') { if (on && !reduce) startParticles(); else stopParticles(); }
    if (key === 'glow' && !on && glow) glow.classList.remove('is-on');
    if (key === 'waifu' && !on && bubble) bubble.classList.remove('is-on');
  }
  Object.keys(defaults).forEach(function (k) {
    // 先统一写好 body class，粒子最后单独启动
    document.body.classList.toggle('fx-' + k + '-off', !state[k]);
  });

  var dockToggle = $('#fx-dock-toggle'), dockPanel = $('#fx-dock-panel');
  if (dockToggle && dockPanel) {
    dockToggle.addEventListener('click', function () {
      var open = dockPanel.hidden;
      dockPanel.hidden = !open;
      dockToggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !dockPanel.hidden) {
        dockPanel.hidden = true;
        dockToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }
  $$('[data-fx-toggle]').forEach(function (input) {
    var key = input.getAttribute('data-fx-toggle');
    if (!(key in defaults)) return;
    input.checked = !!state[key];
    input.addEventListener('change', function () { apply(key, input.checked); save(); });
  });

  // 城市背景可配置；默认路径写在 CSS 里，这里只处理主题自定义
  var cityImage = layer.getAttribute('data-city');
  var cityEl = $('#fx-city');
  if (cityEl && cityImage && cityImage.indexOf('/images/hero-city.webp') === -1) {
    cityEl.style.backgroundImage = 'url("' + cityImage + '")';
  }

  if (state.particles && !reduce) startParticles();
})();
