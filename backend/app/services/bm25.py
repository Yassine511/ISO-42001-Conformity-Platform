"""BM25 lexical search with a French analyzer.

Analyzer: NFC -> casefold -> strip accents -> \\w+ tokens -> drop French
stopwords -> Snowball French stemming. Bm25Index instances are immutable
after construction; the retrieval layer caches them keyed on CONTENT identity
(current version-id set + KB fingerprint — see services/retrieval._bm25_for).
Any cache keyed on something weaker than content would risk serving a stale
index.
"""

import re
import unicodedata

import snowballstemmer
from rank_bm25 import BM25Plus

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
    """BM25 over a list of (result_id, text) pairs.

    Candidates are documents sharing >=1 analyzed token with the query,
    ranked by BM25Plus. Two deliberate choices for tiny corpora, where
    BM25Okapi breaks: candidate filtering uses token overlap (a positivity
    filter empties 1-2 doc corpora), and BM25Plus is used because its IDF is
    nonnegative — Okapi's negative IDF inverted relevance (a doc matching an
    extra rare term ranked BELOW one matching only the common term).
    """

    def __init__(self, entries: list[tuple[str, str]]):
        self._ids = [rid for rid, _ in entries]
        self._token_sets: list[frozenset[str]] = []
        corpus = []
        for _, text in entries:
            tokens = analyze(text)
            corpus.append(tokens)
            self._token_sets.append(frozenset(tokens))
        self._bm25 = BM25Plus(corpus) if corpus else None

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Top-k (result_id, score) among token-overlapping docs; deterministic."""
        if self._bm25 is None:
            return []
        tokens = analyze(query)
        if not tokens:
            return []
        query_set = set(tokens)
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            (
                (rid, float(s))
                for rid, s, toks in zip(self._ids, scores, self._token_sets)
                if query_set & toks
            ),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return ranked[:k]
