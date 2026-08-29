import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
from agentops.mcp.metrics import MCPMetricsTracker

logger = logging.getLogger("agentops.mcp.client")


class SREMCPClient:
    """
    Standardized MCP Client for SRE Agent.
    Supports dynamic tool discovery, structured tool invocation, and metrics tracking.
    """

    def __init__(
        self,
        server: Optional[Any] = None,
        metrics_tracker: Optional[MCPMetricsTracker] = None,
    ):
        self.metrics = metrics_tracker or MCPMetricsTracker()
        if server is None:
            from agentops.mcp.server import create_mcp_server
            self._server = create_mcp_server()
        else:
            self._server = server
        self._discovered_tools: Dict[str, Any] = {}

    def _run_async(self, coro):
        """
        Helper to run async coroutines safely from synchronous context.
        """
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()
            return asyncio.run(coro)
        except Exception as e:
            logger.error(f"Error running async MCP coroutine: {str(e)}")
            raise

    async def discover_tools_async(self) -> List[Dict[str, Any]]:
        """
        Asynchronously discover available tools from the MCP server.
        """
        tools_list = []
        raw_tools = await self._server.list_tools()
        for t in raw_tools:
            name = getattr(t, "name", str(t))
            desc = getattr(t, "description", "")
            schema = getattr(t, "inputSchema", None)
            self._discovered_tools[name] = t
            tools_list.append({
                "name": name,
                "description": desc,
                "input_schema": schema,
            })
        return tools_list

    def discover_tools(self) -> List[Dict[str, Any]]:
        """
        Synchronous tool discovery.
        """
        return self._run_async(self.discover_tools_async())

    async def call_tool_async(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """
        Asynchronously invoke an MCP tool with structured arguments.
        """
        start_time = time.time()
        args = arguments or {}

        try:
            raw_res = await self._server.call_tool(tool_name, args)
            duration = time.time() - start_time

            # Extract structured result from MCP CallToolResult
            data = None
            if hasattr(raw_res, "structured_content") and raw_res.structured_content:
                if isinstance(raw_res.structured_content, dict) and "result" in raw_res.structured_content:
                    data = raw_res.structured_content["result"]
                else:
                    data = raw_res.structured_content
            elif hasattr(raw_res, "content") and raw_res.content:
                texts = []
                for item in raw_res.content:
                    t_text = getattr(item, "text", str(item))
                    try:
                        texts.append(json.loads(t_text))
                    except Exception:
                        texts.append(t_text)
                data = texts[0] if len(texts) == 1 else texts
            else:
                data = raw_res

            self.metrics.record_call(tool_name, duration, success=True)
            return data

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"MCP tool call '{tool_name}' failed: {str(e)}")
            self.metrics.record_call(tool_name, duration, success=False, error=str(e))
            raise

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """
        Synchronous tool invocation.
        """
        return self._run_async(self.call_tool_async(tool_name, arguments))
