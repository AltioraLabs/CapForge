"""CapForge SDK Quickstart Example.

Demonstrates how to use the high-level CapForge SDK to:
1. Decorate Python functions with @capability
2. Register and evaluate capabilities automatically
3. Execute capabilities in an isolated sandbox
4. Export capabilities as standard tool definitions for LLMs
5. Register event webhooks for notifications
"""

from capforge import CapForgeClient, capability

# ---------------------------------------------------------------------------
# 1. Define capabilities using the @capability decorator
# ---------------------------------------------------------------------------


@capability(
    id="sentiment_analyzer",
    name="Sentiment Analyzer",
    domain="nlp",
    risk_level="LOW",
    tags=["nlp", "sentiment", "text"],
    tests=[
        {
            "id": "test_positive",
            "name": "Positive sentiment test",
            "inputs": {"text": "I love using CapForge! It makes agent evolution seamless."},
            "expected_keys": ["sentiment", "score"],
            "assert_expression": "output['sentiment'] == 'positive' and output['score'] > 0.5",
        },
        {
            "id": "test_negative",
            "name": "Negative sentiment test",
            "inputs": {"text": "This pipeline failed with terrible errors and broken dependencies."},
            "expected_keys": ["sentiment", "score"],
            "assert_expression": "output['sentiment'] == 'negative' and output['score'] < 0.5",
        },
    ],
)
def analyze_sentiment(text: str = "") -> dict:
    """Analyze the sentiment of a given input string."""
    positive_words = {"love", "great", "excellent", "awesome", "seamless", "good", "happy"}
    negative_words = {"terrible", "bad", "broken", "failed", "hate", "horrible", "error"}

    words = set(text.lower().split())
    pos_count = len(words & positive_words)
    neg_count = len(words & negative_words)

    if pos_count > neg_count:
        sentiment = "positive"
        score = 0.85
    elif neg_count > pos_count:
        sentiment = "negative"
        score = 0.15
    else:
        sentiment = "neutral"
        score = 0.50

    return {
        "sentiment": sentiment,
        "score": score,
        "positive_word_count": pos_count,
        "negative_word_count": neg_count,
    }


@capability(
    id="currency_converter",
    name="Currency Converter",
    domain="finance",
    risk_level="LOW",
    tags=["finance", "fx", "utility"],
)
def convert_currency(amount: float, from_curr: str = "USD", to_curr: str = "EUR") -> dict:
    """Convert currency using fixed exchange rates."""
    rates = {
        ("USD", "EUR"): 0.92,
        ("EUR", "USD"): 1.09,
        ("USD", "GBP"): 0.79,
        ("GBP", "USD"): 1.27,
    }
    pair = (from_curr.upper(), to_curr.upper())
    rate = rates.get(pair, 1.0)
    converted = round(amount * rate, 2)
    return {
        "original_amount": amount,
        "from_currency": from_curr.upper(),
        "to_currency": to_curr.upper(),
        "converted_amount": converted,
        "exchange_rate": rate,
    }


def main():
    print("=" * 70)
    print("CapForge High-Level SDK Quickstart")
    print("=" * 70)

    # Use CapForgeClient as a context manager
    with CapForgeClient(enable_security_scan=True, auto_evaluate=True) as client:
        # 1. Register Capabilities with automatic test evaluation & promotion
        print("\n[1] Registering capabilities...")
        cap_sent = client.register(analyze_sentiment, promote=True)
        print(f"  -> Registered '{cap_sent.id}' v{cap_sent.version} (status={cap_sent.status.value})")

        cap_curr = client.register(convert_currency, promote=True)
        print(f"  -> Registered '{cap_curr.id}' v{cap_curr.version} (status={cap_curr.status.value})")

        # 2. Export as standard LLM tool definition (OpenAI / Anthropic format)
        print("\n[2] Exporting capability as LLM tool definition...")
        tool_def = client.as_tool("sentiment_analyzer")
        print(f"  Tool Name: {tool_def['function']['name']}")
        print(f"  Description: {tool_def['function']['description']}")
        print(f"  Parameters: {list(tool_def['function']['parameters']['properties'].keys())}")

        # 3. Execute capability in isolated sandbox
        print("\n[3] Executing capability in sandbox...")
        res = client.execute("sentiment_analyzer", {"text": "I love CapForge! It is an awesome framework."})
        print(f"  Execution status: {res.status}")
        print(f"  Execution output: {res.output}")
        print(f"  Execution time:   {res.execution_time_ms} ms")

        # 4. Batch Operations
        print("\n[4] Running batch execution...")
        batch_responses = client.execute_batch(
            [
                {
                    "capability_id": "currency_converter",
                    "inputs": {"amount": 100.0, "from_curr": "USD", "to_curr": "EUR"},
                },
                {
                    "capability_id": "currency_converter",
                    "inputs": {"amount": 50.0, "from_curr": "GBP", "to_curr": "USD"},
                },
            ]
        )
        for r in batch_responses:
            print(f"  Batch item result: {r.output}")

        # 5. Subscribe to Webhook events
        print("\n[5] Registering event webhook...")
        sub = client.subscribe_webhook(
            url="https://myapp.com/events/capforge",
            events=["skill_promoted", "task_failed"],
            secret="my_hmac_secret_key",
            description="Slack Notification Channel",
        )
        print(f"  Subscribed webhook ID: {sub.id}")
        print(f"  Active: {sub.active}, Filter: {sub.events}")

        # 6. Instance Health Check
        print("\n[6] Subsystem health check...")
        health = client.health_check()
        print(f"  Version: {health['version']}")
        print(f"  Subsystems: {health['subsystems']}")

    print("\n" + "=" * 70)
    print("CapForge SDK Quickstart Completed Successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
