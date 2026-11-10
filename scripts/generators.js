/* 自定义 generator：本地搜索索引 + Atom feed
   不装额外 npm 插件，保证 CI 构建依赖尽量少。
   放在 Hexo 项目的 scripts/ 目录，Hexo 启动时自动加载。 */

var strip = function (html) {
  return String(html || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/&#\d+;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

var esc = function (s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

var absolute = function (cfg, path) {
  var root = cfg.root || '/';
  return (cfg.url || '').replace(/\/$/, '') + (root + path).replace(/\/{2,}/g, '/');
};

hexo.extend.generator.register('local_search_json', function (locals) {
  var cfg = hexo.config;
  var posts = locals.posts.sort('-date').toArray();
  var data = posts.map(function (p) {
    return {
      title: p.title || '',
      date: p.date ? p.date.format('YYYY-MM-DD') : '',
      url: '/' + p.path,
      text: strip(p.content).slice(0, 2400),
      tags: p.tags ? p.tags.toArray().map(function (t) { return t.name; }) : [],
      categories: p.categories ? p.categories.toArray().map(function (c) { return c.name; }) : []
    };
  });
  return { path: 'search.json', data: JSON.stringify(data) };
});

hexo.extend.generator.register('atom_feed', function (locals) {
  var cfg = hexo.config;
  var limit = (cfg.feed && cfg.feed.limit) || 20;
  var posts = locals.posts.sort('-date').limit(limit).toArray();
  var siteUrl = (cfg.url || '').replace(/\/$/, '');
  var updated = posts.length ? posts[0].date.toISOString() : new Date().toISOString();

  var entries = posts.map(function (p) {
    var url = absolute(cfg, p.path);
    var summary = strip(p.excerpt || p.content).slice(0, 320);
    return [
      '  <entry>',
      '    <title>' + esc(p.title) + '</title>',
      '    <link href="' + esc(url) + '" />',
      '    <id>' + esc(url) + '</id>',
      '    <published>' + p.date.toISOString() + '</published>',
      '    <updated>' + (p.updated ? p.updated.toISOString() : p.date.toISOString()) + '</updated>',
      '    <author><name>' + esc(cfg.author) + '</name></author>',
      '    <summary type="html">' + esc(summary) + '</summary>',
      '  </entry>'
    ].join('\n');
  }).join('\n');

  var xml = [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<feed xmlns="http://www.w3.org/2005/Atom">',
    '  <title>' + esc(cfg.title) + '</title>',
    '  <subtitle>' + esc(cfg.description) + '</subtitle>',
    '  <link href="' + esc(siteUrl + '/atom.xml') + '" rel="self" />',
    '  <link href="' + esc(siteUrl + '/') + '" />',
    '  <id>' + esc(siteUrl + '/') + '</id>',
    '  <updated>' + updated + '</updated>',
    '  <author><name>' + esc(cfg.author) + '</name></author>',
    entries,
    '</feed>'
  ].join('\n');

  return { path: 'atom.xml', data: xml };
});
