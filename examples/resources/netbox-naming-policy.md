# NetBox IPAM Naming Policy (demo resource)

An agent registering addresses through the NetBox bridge MUST follow these rules:

1. **dns_name** is the bare hostname, lowercase, no domain suffix (`worker1`, not `Worker1.lan`).
2. **description** states the node's role and architecture, e.g. `worker1 (amd64 node)`.
3. Addresses are registered with their prefix length (`/24`), never bare IPs.
4. **status** is `active` for nodes currently in service; use `reserved` for planned capacity.
5. Never delete an address you did not create in the same session — flag it instead.

Serve this file to agents via:

```
ADDITIONAL_RESOURCES="netbox-naming-policy=/path/to/netbox-naming-policy.md"
```
