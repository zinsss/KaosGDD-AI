FROM kaosgdd-memos-web:0.1.5-trusted-host1

COPY rectangular-controls.css /tmp/kaos-memos-rectangular-controls.css

RUN set -eu; \
  css_file="$(find /usr/share/nginx/html/assets -maxdepth 1 -type f -name 'index-*.css' | sort | head -n 1)"; \
  test -n "${css_file}"; \
  printf '\n/* KaosGDD rectangular-control override. */\n' >> "${css_file}"; \
  cat /tmp/kaos-memos-rectangular-controls.css >> "${css_file}"; \
  rm /tmp/kaos-memos-rectangular-controls.css
