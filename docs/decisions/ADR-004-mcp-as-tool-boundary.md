# ADR-004: Model Context Protocol (MCP) as the Standardized Tool Boundary

## Status
Accepted

## Context
In Milestone v0.2, the AI SRE Agent invoked local Python helper classes (`KubernetesInvestigationTools`, `PrometheusInvestigationTools`, `LokiInvestigationTools`) directly in-process. While functional, direct hard-coded Python bindings present significant long-term drawbacks:
1. **Lack of Protocol Standardization**: Hard-coded Python function calls couple the agent directly to specific library implementations.
2. **Tool Discovery & Schema Evolution**: Agents cannot dynamically discover new investigation capabilities or inspect tool input schemas without modifying core orchestration code.
3. **Impediment to Security Governance**: Without a standardized protocol boundary, inserting authorization checks, rate limiting, and capability-based access control requires intrusive changes across business logic.

## Decision
We established the **Model Context Protocol (MCP)** as the standardized, decoupled tool boundary in Milestone v0.3:
1. **MCP Server as Tool Provider**: A dedicated `MCPServer` (`agentops-sre-investigation-tools`) registers and exposes the 8 read-only infrastructure tools (`k8s_*`, `prom_*`, `loki_*`).
2. **MCP Client for the SRE Agent**: The `SREAgent` connects strictly through `SREMCPClient`, discovers available tools via MCP discovery (`list_tools`), and executes tool calls (`call_tool`) over JSON-RPC.
3. **MCP is the Tool Boundary, NOT the Authorization Boundary**:
   - MCP standardizes tool contracts, schemas, serializations, and discovery.
   - MCP itself does *not* enforce security policies, tenant isolation, or capability-based authorization tokens. That policy enforcement belongs in the **Security Gateway** (Milestone v0.4), which will sit between the MCP Client and MCP Server.

## Consequences
- **Decoupling**: Telemetry backends (Kubernetes API, Prometheus, Loki) are completely isolated behind clean MCP tool schemas.
- **Dynamic Discovery**: The agent inspects available tools at runtime rather than relying on a rigid hard-coded registry.
- **Zero Rewrite of Clients**: The underlying v0.2 telemetry clients remain intact as the execution engine wrapped by the MCP server.
- **Clear Path for v0.4**: Setting up the MCP boundary now allows v0.4 to introduce a proxying/intercepting Policy and Security Gateway seamlessly without altering tool implementations.
