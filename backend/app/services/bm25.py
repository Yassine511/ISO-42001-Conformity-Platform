"""BM25 lexical search with a French analyzer.

Analyzer: NFC -> casefold -> strip accents -> \\w+ tokens -> drop French
stopwords -> Snowball French stemming. The index is rebuilt per request —
the corpus is tiny, and any cache keyed on something weaker than content
would risk serving a stale index.
"""

import re
import unicodedata

import snowballstemmer
from rank_bm25 import BM25Okapi

_STEMMER = snowballstemmer.stemmer("french")
_TOKEN = re.compile(r"\w+", re.UNICODE)

# Compact standard French stopword list (accent-stripped, casefolded).
FRENCH_STOPWORDS = frozenset(
    """a afin ai ainsi apres au aucun aussi autre autres aux avant avec avoir
    c ca car ce cela celle celles celui ces cet cette ceux chaque ci comme
    d dans de des du donc dont
    elle elles en encore entre est et etaient etait etant etc etre eu eux
    fait faites fois font
    il ils j je l la le les leur leurs lors lui
    m ma mais me meme memes mes moi mon
    n ne ni nos notre nous
    on ont ou
    par parce pas peu peut plus pour puis
    qu que quel quelle quelles quels qui quoi
    s sa sans se selon ses si sinon soi soit son sont sous sur
    t ta te tel telle telles tels tes toi ton tous tout toute toutes tres tu
    un une
    va vers voici voila vos votre vous
    y""".split()
)


def analyze(text: str) -> list[str]:
    """Normalize French text into stemmed search tokens."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    tokens = [t for t in _TOKEN.findall(text) if t not in FRENCH_STOPWORDS]
    return _STEMMER.stemWords(tokens)


class Bm25Index:
    """BM25 over a list of (result_id, text) pairs."""

    def __init__(self, entries: list[tuple[str, str]]):
        self._ids = [rid for rid, _ in entries]
        corpus = [analyze(text) for _, text in entries]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Top-k (result_id, score), score > 0 only; deterministic order."""
        if self._bm25 is None:
            return []
        tokens = analyze(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            ((rid, float(s)) for rid, s in zip(self._ids, scores) if s > 0),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return ranked[:k]
