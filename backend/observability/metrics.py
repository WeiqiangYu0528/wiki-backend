"""All Prometheus/OTEL metric definitions for the agent system."""

from observability.tracing import get_meter


class AgentMetrics:
    """Container for all agent observability metrics.

    Instantiate once at startup. Each attribute is a meter instrument.
    """

    def __init__(self) -> None:
        meter = get_meter()

        # --- Counters ---
        self.requests_total = meter.create_counter(
            "agent_requests_total",
            description="Total agent requests",
        )
        self.llm_calls_total = meter.create_counter(
            "agent_llm_calls_total",
            description="Total LLM invocations",
        )
        self.tool_calls_total = meter.create_counter(
            "agent_tool_calls_total",
            description="Total tool invocations",
        )
        self.search_calls_total = meter.create_counter(
            "agent_search_calls_total",
            description="Total search calls by tier",
        )
        self.embedding_calls_total = meter.create_counter(
            "agent_embedding_calls_total",
            description="Total embedding API calls",
        )
        self.tokens_total = meter.create_counter(
            "agent_tokens_total",
            description="Total tokens consumed",
        )
        self.errors_total = meter.create_counter(
            "agent_errors_total",
            description="Total errors by stage",
        )

        # --- Histograms ---
        self.request_duration = meter.create_histogram(
            "agent_request_duration_seconds",
            description="End-to-end request latency",
            unit="s",
        )
        self.llm_call_duration = meter.create_histogram(
            "agent_llm_call_duration_seconds",
            description="Per-LLM-call latency",
            unit="s",
        )
        self.tool_call_duration = meter.create_histogram(
            "agent_tool_call_duration_seconds",
            description="Per-tool-call latency",
            unit="s",
        )
        self.prompt_tokens_hist = meter.create_histogram(
            "agent_prompt_tokens",
            description="Prompt size in estimated tokens",
        )
        self.search_results_hist = meter.create_histogram(
            "agent_search_results_count",
            description="Number of search results returned",
        )
        self.retrieval_chars_hist = meter.create_histogram(
            "agent_retrieval_chars",
            description="Characters of retrieved content injected into prompt",
        )

        # --- Up-Down Counters (gauges) ---
        self.embedding_cache_size = meter.create_up_down_counter(
            "agent_embedding_cache_size",
            description="Current embedding cache entries",
        )
