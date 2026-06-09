# 7. Frontend deep-dive (Nginx)

## 7.1 What the frontend is (and isn't)

The SSMS frontend is intentionally **simple**: vanilla HTML / CSS / JavaScript
files in a directory, served by an Nginx container. There is no build step,
no Webpack, no React, no TypeScript transpilation.

Why so simple?

- A DevSecOps project's job is to demonstrate the pipeline, not show off
  a frontend stack.
- Static files are the easiest to ship securely (no Node runtime, no npm
  CVE noise, tiny image).
- Pure JS + `fetch` against the backend keeps every layer observable in
  the browser dev-tools, which makes the demo and the explanation easier.

The pages are:

| File              | Purpose                                              |
|-------------------|------------------------------------------------------|
| `index.html`      | Operator dashboard: sales/stock KPIs, alerts         |
| `shop.html`       | Anonymous click-and-collect catalogue                |
| `scanner.html`    | Barcode-scanner UI for employees                     |
| `app.js`          | Common JS (auth helpers, fetch wrappers)             |
| `shop.js`         | Catalogue/cart logic for shop page                   |
| `style.css` / `shop.css` | Standard CSS                                  |

## 7.2 Nginx — what is it doing here?

Nginx in this project does **one** thing: serve files from
`/usr/share/nginx/html`. It is **not** acting as a reverse proxy in front
of the backend (a common, valid alternative architecture — see 7.6).

The runtime image is `nginxinc/nginx-unprivileged:1.27-alpine`, which is the
official Nginx team's hardened variant:

- Runs as uid 101, never as root.
- Listens on port 8080 by default (since unprivileged users can't bind to
  ports < 1024 on Linux).
- Same configuration files as upstream `nginx:alpine`, identical features.

The default config inside the image serves `/usr/share/nginx/html` on
port 8080. Our Dockerfile just copies the static files into that path —
nothing else.

## 7.3 The Dockerfile

```dockerfile
FROM nginxinc/nginx-unprivileged:1.27-alpine
USER 101
COPY --chown=101:101 . /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
```

- `USER 101` — Nginx runs under that uid the whole time.
- `--chown=101:101` on the COPY — every file is owned by nginx's uid so
  Nginx can read them without world-readable permissions.
- `wget`-based healthcheck — Alpine images ship wget, not curl.
- `EXPOSE 8080` — declares the listening port for tooling.

## 7.4 The compose binding

```yaml
frontend:
  build: ./frontend
  image: ssms/frontend:latest
  ports: [ "80:8080" ]                  # host 80 -> container 8080
  cap_drop: [ ALL ]
  security_opt: [ "no-new-privileges:true" ]
  networks: [ ssms_net ]
```

The kernel-level magic of port 80 binding (which usually requires root)
happens at the **host** boundary, not inside the container. Docker's port
publication uses `iptables` rules on the host that NAT incoming `:80` to
the container's `:8080`. The container itself, running as uid 101, only
ever listens on a high port. We get the "user sees port 80" UX while the
container stays unprivileged.

## 7.5 Frontend ↔ backend communication

`shop.js` and friends use the `fetch` API directly against the backend:

```js
async function loadStock() {
  const r = await fetch(`http://${location.hostname}:8000/inventory`);
  return r.json();
}
```

Notes:

- The browser computes `location.hostname` dynamically, so the same code
  works locally (`127.0.0.1:8000`) and in production (`13.39.86.185:8000`).
- The cross-origin request (`:80` → `:8000`) is allowed because FastAPI
  ships permissive CORS (`allow_origins=["*"]`) for the demo. **Production
  hardening** would scope it (`allow_origins=["https://shop.example.com"]`).
- The JWT for authenticated calls lives in `localStorage` after a successful
  `/auth/login`. `app.js` injects `Authorization: Bearer <token>` on every
  protected fetch.

A cleaner architecture would route everything through Nginx so the browser
only ever sees one origin (see 7.6). For the demo we kept the two ports
explicit so the architecture diagram matches the code.

## 7.6 The reverse-proxy alternative (not used here)

Many production stacks put Nginx in **reverse-proxy** mode in front of the
backend:

```
Browser → Nginx :80
            │
            ├─ /api/* → http://backend:8000/  (proxy_pass)
            └─ /     → /usr/share/nginx/html (static)
```

Pros:

- Single origin: no CORS needed.
- TLS terminates once at the front.
- Static caching, gzip, rate limiting at the proxy.
- The backend can stay on a non-published port (`expose: ["8000"]` instead
  of `ports: ["8000:8000"]`).

Cons:

- One more config file (`nginx.conf` with `proxy_pass`).
- Less obvious to a reader skimming the diagram.

This is the **easy follow-up hardening** to mention in an oral defense:
"In production I'd add an `nginx.conf` with `proxy_pass /api/ to backend:8000`,
close port 8000 in the security group, and put a Let's Encrypt sidecar in
front for TLS." That single change moves the project a long way toward
production-grade.

## 7.7 Static asset serving in the backend (fallback path)

A subtle detail: the **backend container** also has the frontend mounted
read-only at `/app/frontend`:

```yaml
backend:
  volumes:
    - ./frontend:/app/frontend:ro
```

In `main.py`:

```python
_FRONTEND_CANDIDATES = [
    os.path.normpath(os.path.join(_HERE, "..", "..", "frontend")),
    "/app/frontend",
]
FRONTEND_DIR = next((p for p in _FRONTEND_CANDIDATES if os.path.isdir(p)), None)

if FRONTEND_DIR:
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    @app.get("/")        ...returns index.html...
    @app.get("/shop")    ...returns shop.html...
    @app.get("/scanner") ...returns scanner.html...
```

This makes `http://<EC2>:8000/` also serve the frontend. Useful when:

- The nginx container isn't running (early in deployment).
- Someone is doing a backend-only demo and doesn't want to start nginx.
- A test on `:8000/shop` needs to work in CI without spinning up nginx.

So there are **two** ways to reach the shop UI in this project:

```
http://<EC2>/         → nginx serves /usr/share/nginx/html/index.html
http://<EC2>:8000/    → FastAPI serves the same file directly
```

Both are equivalent; the first is what end-users use, the second is a
diagnostic fallback.

## 7.8 Frontend security posture

| Concern                       | What we do                                                          |
|-------------------------------|---------------------------------------------------------------------|
| Running as root in container  | Mitigated: uid 101 in `nginx-unprivileged`                          |
| XSS in user-rendered content  | All dynamic content is interpolated with `textContent`, not `innerHTML` |
| CSRF                          | JWT bearer in `Authorization` header (not cookies) — CSRF not applicable |
| Token theft via XSS           | Mitigated by no-`innerHTML` rule + no third-party JS                |
| Mixed content / TLS           | Not yet — production needs HTTPS termination                        |
| Open CORS                     | `allow_origins=["*"]` is demo-only; tighten in production           |
| Content Security Policy (CSP) | Could add `Content-Security-Policy: default-src 'self'` via Nginx config |
| Clickjacking                  | Could add `X-Frame-Options: DENY`; trivial follow-up                |

The first three are real defenses we ship. The rest are documented gaps
in section 14 (Risk analysis).
