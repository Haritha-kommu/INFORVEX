import json


def build_article_event(article: dict) -> str:
    return json.dumps({"event_type": "article.retrieved", "article": article}, default=str)


def publish_article(article: dict, bootstrap_servers: str) -> bool:
    try:
        from kafka import KafkaProducer
        producer = KafkaProducer(bootstrap_servers=bootstrap_servers, value_serializer=lambda value: value.encode())
        producer.send("newsphere.articles", build_article_event(article))
        producer.flush()
        return True
    except (ImportError, OSError, TimeoutError):
        return False
