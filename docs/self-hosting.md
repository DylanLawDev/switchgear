# Self-hosting

The supported portable topology is exactly one application container with one
persistent `/data` mount. SQLite, local scheduling, and inline workflow continuation
are intentionally single-instance. Configure your host to restart the container and
back up the volume.

Compose binds to `127.0.0.1`. For remote access, terminate TLS in Caddy, nginx, or
another reverse proxy and forward to that loopback port. Set `SWITCHGEAR_PUBLIC_BASE_URL`
to the HTTPS origin and keep `SWITCHGEAR_COOKIE_SECURE=true`. Never publish an
unauthenticated instance.

Seed directories (`skills`, `workflows`, `agents`, `resources`, and `channels`) are
read-only inputs. Skills and agents are inserted only when missing. Workflows sourced
from the repository are refreshed while preserving status; owner-edited definitions
are not overwritten. Seed resources update only while their source remains `seed`.

At startup the service creates the state directory and performs a write probe. A
read-only or incorrectly owned mount fails with a clear error before traffic starts.
