# Deployment integrations

The core image requires only a persistent volume and one replica. Suitable targets
include a VM, NAS, home server, or a container platform that provides persistent
single-writer storage.

Provider adapters are lazy and optional. Deployment repositories should configure
adapters through environment inputs, keep credentials in a secret manager, and pin
immutable application versions.

Multi-replica deployments are not supported. They require shared transactional
storage, a durable queue, distributed scheduler ownership, shared artifact storage,
coordination, and concurrency recovery tests.
