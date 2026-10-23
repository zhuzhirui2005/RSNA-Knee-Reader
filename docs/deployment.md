# Deployment

## Local clients

Use stdio when the client can start a process on the machine holding the data. The server writes MCP messages to stdout; application/server diagnostics use stderr. No network listener is needed.

## Remote clients

Run HTTP on the data server, then expose it through a TLS reverse proxy or a tunnel that you control. Start with a loopback listener:

```sh
export RSNA_READER_TOKEN='set-a-long-random-secret-outside-the-repository'
rsna-knee-reader serve --catalog /srv/reader/catalog.json --data-root /srv/reader/dicom --archives /srv/reader/archives --transport http --public-host reader.example.org
```

For PowerShell, set `$env:RSNA_READER_TOKEN` instead of `export`. The client sends `Authorization: Bearer <token>`. The same token protects `/healthz`. Tokens are read from the process environment and are never placed in the example configuration.

`--public-host` allows the specified HTTP Host and HTTPS Origin through the SDK's transport checks. It does not create DNS, TLS, or a tunnel. If a local reverse proxy preserves the external Host header, supply that hostname here. Connect to `/mcp`, not `/sse`.

Some hosted MCP clients require OAuth rather than a static authorization header. This package does not implement an OAuth authorization server: use a compatible authenticated gateway for those clients. It also does not include the account-specific tunnel client used during the competition. The standard reader endpoint is independent of that transport.

The [MCP SDK documentation](https://py.sdk.modelcontextprotocol.io/run/) describes supported transports. The SDK handles modern discovery and legacy initialization on the same Streamable HTTP endpoint. Both paths are exercised by this project's tests.

## Container

```sh
docker build -t rsna-knee-reader .
docker run --rm -p 127.0.0.1:8768:8768 -v /absolute/reader-data:/data:ro -e RSNA_READER_TOKEN rsna-knee-reader
```

The mounted directory contains `catalog.json`, `dicom/`, and optionally `archives/`. The container reads data as an unprivileged user; grant that user read access to the mounted files. To preserve an external Host header, append the full `serve` command with `--public-host` to your container invocation.

## Operating the reader

- Keep pages small and use one outstanding request per case. Scale across independent cases rather than queuing many image responses from one case.
- Large native images can still exceed a client's image limit. Request a crop in native coordinates for that detail.
- For a tool error, check server stderr and retry the same slice position after the underlying issue is fixed. Do not advance `start` based on a failed response.
- A proxy 429 or a failed connection probe is a transport/client problem; this package does not manufacture a successful read in response.
- Reuse the client's connection. Repeated discovery between every page is unnecessary for this stateless reader.
