# Private Tailscale Access

Lyra remains bound to `127.0.0.1:8765`. Tailscale Serve publishes that
loopback service through tailnet-only HTTPS without opening Lyra's raw port to
the LAN or tailnet.

## Current route

```text
https://aurora.tail1ce71c.ts.net/ -> http://127.0.0.1:8765
```

Everwood's direct tailnet route on port `5173` is separate and is not changed
by this configuration.

## Why Serve needs separate authorization

Tailscale supports two relevant private network paths:

1. **Direct tailnet port:** the application listens on a host interface and a
   peer connects to `http://host:port`. Tailscale encrypts traffic between
   devices, but the application port may also be reachable from the LAN when
   it is bound to `0.0.0.0` or `::`. The browser sees ordinary HTTP. Everwood's
   current `5173` frontend and `8000` API use this path.
2. **Tailscale Serve:** the application remains on loopback. Tailscale accepts
   authenticated tailnet HTTPS and reverse-proxies it to the local target.
   Enabling Serve is a tailnet-level capability, so an administrator must
   authorize it once. Lyra uses this path.

The resulting Lyra path is:

```text
enrolled browser -> tailnet HTTPS :443 -> Tailscale Serve
                 -> loopback HTTP 127.0.0.1:8765 -> Lyra
```

Serve does not make an application public. Funnel is the separate public
ingress feature and remains prohibited. Databases should never be published
through either web route; keep their host mappings on loopback or internal
container networks unless a separately authenticated database-access design
requires otherwise.

## Verify

Run from an elevated PowerShell prompt because the Windows Tailscale named
pipe is administrator-protected:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' status
& 'C:\Program Files\Tailscale\tailscale.exe' serve status
& 'C:\Program Files\Tailscale\tailscale.exe' funnel status
```

The Serve and Funnel status output must label the route `tailnet only`. Funnel
must never be enabled for Lyra. The application health endpoint should respond
through HTTPS:

```powershell
Invoke-RestMethod 'https://aurora.tail1ce71c.ts.net/api/health'
```

The raw tailnet address must not accept Lyra's internal port:

```powershell
Test-NetConnection 100.100.121.116 -Port 8765
```

`TcpTestSucceeded` must be `False`.

## Authority boundary

The remote route permits normal web conversation. `/control` and every
`/api/control/*` operation remain workstation-local and reject Tailscale or
other proxied requests even if the caller supplies the correct control token.
Telegram's authority boundary is unchanged.

At initial validation the tailnet contained only Christopher-owned devices. If
another person or account is ever invited, restrict this node with a Tailscale
access-control policy before continuing to expose Lyra.

## Disable or restore

Disable only the HTTPS proxy:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --https=443 off
```

Restore the approved route:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --bg --yes http://127.0.0.1:8765
```

Do not use `tailscale funnel` for this service.
