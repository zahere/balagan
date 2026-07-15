"""Framework adapters — chaos-test meshes built in other frameworks.

Importing this package registers adapter topologies into
`balagan.topology.PROTOCOLS` (e.g. lg-flat, lg-hierarchical, lg-ring).
"""

from balagan.adapters import langgraph_mesh  # noqa: F401
