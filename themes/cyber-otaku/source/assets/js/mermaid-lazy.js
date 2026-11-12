/*
 * mermaid-lazy.js — 懒加载渲染软考笔记里的 ```mermaid 图。
 *
 * 注意：Hexo 的高亮器会把 ```mermaid 当成未知语言，最终输出成
 * figure.highlight.plaintext（<mermaid> 类名在 HTML 里被丢弃，且结构里没有 <code>），
 * 所以不能用 class="language-mermaid" 选取。这里改为按「内容特征」识别：
 * 扫描 figure.highlight 内的代码块，首行以 mermaid 图类型关键字开头的即视为 mermaid。
 *
 * 仅当存在此类块时才从 CDN 拉取 mermaid，多 CDN 回退（jsdelivr -> unpkg -> cdnjs），
 * 全部失败时降级为代码块。默认 dark 主题匹配赛博终端风；securityLevel: loose 允许节点内 <br>。
 */
(function () {
  var CDNS = [
    '/vendor/mermaid.min.js',
    'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js',
    'https://unpkg.com/mermaid@10.9.1/dist/mermaid.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js'
  ];

  // mermaid 图类型的首行关键字
  var MERMAID_RE = /^\s*(flowchart|graph|sequenceDiagram|mindmap|classDiagram|stateDiagram(?:-v2)?|gantt|pie|erDiagram|journey|gitgraph|timeline|quadrantChart|requirementDiagram|C4Context|C4Container|C4Component)\b/;

  function collectMermaid() {
    var figs = document.querySelectorAll('figure.highlight');
    var blocks = [];
    figs.forEach(function (fig) {
      var pre = fig.querySelector('pre');
      if (!pre) return;
      var text = pre.textContent || '';
      var firstLine = (text.split('\n').map(function (l) { return l.trim(); }).filter(Boolean)[0]) || '';
      if (MERMAID_RE.test(firstLine)) {
        blocks.push({ fig: fig, text: text });
      }
    });
    return blocks;
  }

  function renderMermaid() {
    var blocks = collectMermaid();
    if (!blocks.length) return;

    function load(i) {
      if (i >= CDNS.length) {
        console.warn('[mermaid] 所有 CDN 均加载失败，已降级为代码块显示');
        return;
      }
      var s = document.createElement('script');
      s.src = CDNS[i];
      s.onload = function () {
        try {
          window.mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            securityLevel: 'loose'
          });
          blocks.forEach(function (b) {
            var div = document.createElement('div');
            div.className = 'mermaid';
            div.textContent = b.text;
            if (b.fig && b.fig.parentNode) {
              b.fig.parentNode.replaceChild(div, b.fig);
            }
          });
          window.mermaid.run();
        } catch (e) {
          console.warn('[mermaid] 渲染失败：', e);
        }
      };
      s.onerror = function () { load(i + 1); };
      document.head.appendChild(s);
    }

    load(0);
  }

  if (document.readyState !== 'loading') {
    renderMermaid();
  } else {
    document.addEventListener('DOMContentLoaded', renderMermaid);
  }
})();
