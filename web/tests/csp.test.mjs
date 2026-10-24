import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

for (const page of ['index.html', 'read.html']) {
  const html = readFileSync(new URL(`../${page}`, import.meta.url), 'utf8').replace(/\r\n?/g, '\n');

  test(`${page}: PAT page CSP restricts scripts and network destinations`, () => {
    const metas = [...html.matchAll(/<meta\b[^>]*http-equiv="Content-Security-Policy"[^>]*>/gi)];
    assert.equal(metas.length, 1, 'exactly one CSP meta is required');
    assert.ok(metas[0].index < html.search(/<(?:link|style|script)\b/i), 'CSP must precede resources');
    const content = metas[0][0].match(/\bcontent="([^"]+)"/i)?.[1];
    assert.ok(content, 'CSP meta must have a policy');
    const directives = new Map();
    for (const clause of content.split(';').map((s) => s.trim()).filter(Boolean)) {
      const [name, ...sources] = clause.split(/\s+/);
      assert.ok(!directives.has(name), `duplicate directive: ${name}`);
      directives.set(name, sources);
    }
    const required = {
      'default-src': ["'none'"],
      'script-src': ["'self'"],
      'connect-src': ['https://api.github.com'],
      'object-src': ["'none'"],
      'base-uri': ["'none'"],
      'form-action': ["'self'"],
      'img-src': ["'self'"],
      'style-src-attr': ["'none'"],
      'manifest-src': ["'self'"],
      'worker-src': [page === 'index.html' ? "'self'" : "'none'"],
    };
    for (const [directive, sources] of Object.entries(required)) {
      assert.deepEqual(directives.get(directive), sources, directive);
    }
    assert.ok(directives.get('script-src').every((source) => !/unsafe-/i.test(source)));
    assert.ok(!directives.has('script-src-elem'), 'do not override script-src for elements');
    assert.ok(!directives.has('script-src-attr'), 'do not override script-src for handlers');
    assert.ok(!directives.has('frame-ancestors'), 'frame-ancestors requires an HTTP header, not meta');
    assert.match(html, /<!--[\s\S]*?frame-ancestors[\s\S]*?-->/);

    const styleHashes = [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].map(([, css]) =>
      `'sha256-${createHash('sha256').update(css).digest('base64')}'`);
    assert.deepEqual(directives.get('style-src'), ["'self'", ...styleHashes], 'allow only local CSS and exact inline styles');
    assert.ok(!directives.has('style-src-elem'), 'do not override the stylesheet hashes');
  });

  test(`${page}: no inline scripts, event handlers or style attributes need exceptions`, () => {
    const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
    assert.equal(scripts.length, 1);
    assert.match(scripts[0][1], new RegExp(`\\bsrc="${page === 'index.html' ? 'app' : 'read'}\\.js"`));
    assert.equal(scripts[0][2].trim(), '');
    assert.doesNotMatch(html, /\son\w+\s*=/i);
    assert.doesNotMatch(html, /\sstyle\s*=/i);
    assert.doesNotMatch(html, /(?:src|href)\s*=\s*["'](?:javascript|data|blob):/i);
  });
}
