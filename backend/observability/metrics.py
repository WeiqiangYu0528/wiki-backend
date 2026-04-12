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

        # --- Search strategy metrics ---
        self.search_attempts_total = meter.create_counter(
            "agent_search_attempts_total",
            description="Total search attempts by strategy",
        )
        self.strategy_escalations_total = meter.create_counter(
            "agent_strategy_escalations_total",
            description="Search strategy escalation events",
        )
        self.loops_detected_total = meter.create_counter(
            "agent_loops_detected_total",
            description="Loop detection events (recursion limit hit)",
        )
        self.repo_confidence_total = meter.create_counter(
            "agent_repo_confidence_total",
            description="Repo targeting confidence distribution",
        )
        self.code_search_success_total = meter.create_counter(
            "agent_code_search_success_total",
            description="Successful code search lookups",
        )
        self.code_search_latency = meter.create_histogram(
            "agent_code_search_duration_seconds",
            description="Latency for code search operations",
            unit="s",
        )
        self.recursion_depth = meter.create_histogram(
            "agent_recursion_depth",
            description="How deep the ReAct loop goes per request",
        )
