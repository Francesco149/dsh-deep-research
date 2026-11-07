# Search

Workers search through `skill/deep-research/scripts/search` (bash), not dsh's `web_search`. The base dsh bundle's
only search provider is DeepSeek's (a paid DeepSeek model turn per search), and the helper lets the run use
whatever engines you have keys for, in quality order, falling through on errors and rate limits.

```sh
search "QUERY" [--max N] [--engine auto|all|exa|ddg|vertex|free|langsearch|deepseek] [--region us-en] [--timelimit d|w|m|y]
```

Order (`--engine auto`): **Exa → DuckDuckGo → Vertex (Gemini + Google Search) → other free engines (Brave, Bing,
Mojeek, Yahoo via ddgs) → LangSearch**. An engine without its key is skipped. One that errors or returns nothing
hands over to the next. The output names the engine that answered.

| engine | key (environment) | cost | blind score (0–10) |
|---|---|---|---|
| Exa | `EXA_API_KEY` (has free credits) | ~$0.007 a search, ~$0.30 for a whole 46-search run | **8.25** both times, best on 11 of 12 queries, primary sources on top |
| DuckDuckGo | none | free, rate-limited scraping | 7.17 / 7.33 |
| Vertex AI, Gemini with Google Search grounding | gcloud application-default credentials, `GOOGLE_CLOUD_PROJECT` | Vertex pricing | 6.42: always answers, but fewer results, bare-domain titles, model-written blurbs that can misname a source (trust the URL); retries once when the model skips the search |
| free pool (Brave, Bing, Mojeek, Yahoo) | none | free | 6.5–7.0 on the 4 queries it answered, throttled on the rest |
| LangSearch | `LANGSEARCH_API_KEY` | free credits | 2.83 / 3.0: off-topic, spun spam. Last resort |
| DeepSeek native search | `DEEPSEEK_API_KEY` | a model turn per search | not evaluated; by name only |

**With no keys at all**, the helper runs on DuckDuckGo and the free pool. That works, but expect throttling on a
long run. An Exa key is the single biggest quality improvement for the least money.

Keys go in `~/.config/dsh/search.env` (one `NAME=value` per line, mode 600), which the generated systemd unit
loads. Run dsh some other way and you must put them into its environment yourself.

## How the order was chosen

Twelve research-style queries were used: hardware support matrices, a BIOS/memory-tuning question, CUDA and ZFS
internals, quant comparisons, a trading-card set list, an Italian tax question, and a query about a product
release that does not exist (a trap for engines that make things up). Each engine's top 10 was collected. A judge
model saw only **shuffled, anonymised lists** (A, B, C, ...) and scored each 0–10 for how well it would serve a
researcher: primary sources, relevance, duplication, spam. The test ran twice with different shuffles. The scores
above are the means.

## Using dsh's own web_search instead

If you configure a dsh search provider (DeepSeek, Exa or Perplexity plugins), set `"search": "web_search"` in the
layout. The skill then tells workers to use `web_search` and fall back to the helper when it errors. Its results
are leads either way: workers read the page with `fetch` before citing it.
