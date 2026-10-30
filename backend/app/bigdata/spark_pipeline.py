"""Optional batch processors.

``process_jsonl`` is the functioning standard-library processor used without
Spark. ``process_with_pyspark`` is a separate lazy optional implementation and
requires an independently installed and configured PySpark runtime.
"""
import json
from collections import Counter
from pathlib import Path

from ..agents.database_management import normalize_url


def process_jsonl(input_path: str, output_path: str) -> dict:
    records = [json.loads(line) for line in Path(input_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    unique = {
        normalize_url(record["canonical_url"]): record
        for record in records
        if record.get("canonical_url")
    }
    summary = Counter((record.get("category", "Other"), record.get("source_name", "Unknown")) for record in unique.values())
    output = {"records": len(unique), "counts": [{"category": key[0], "source": key[1], "count": value} for key, value in summary.items()]}
    Path(output_path).write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def process_with_pyspark(input_path: str, output_path: str) -> None:
    """Run the optional Spark equivalent against JSONL input."""
    try:
        from pyspark.sql import SparkSession
        from pyspark.sql.functions import coalesce, lit, to_date
    except ImportError as exc:
        raise RuntimeError("PySpark is not installed; use process_jsonl or install the optional Spark dependency") from exc

    spark = SparkSession.builder.appName("NewsSphereBatch").getOrCreate()
    try:
        records = spark.read.json(input_path).dropDuplicates(["canonical_url"])
        result = (
            records.withColumn("collection_date", to_date(coalesce("publication_time", lit("unknown"))))
            .groupBy("category", "source_name", "collection_date")
            .count()
        )
        result.write.mode("overwrite").json(output_path)
    finally:
        spark.stop()
