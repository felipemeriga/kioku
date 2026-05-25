# TF-IDF: Term Frequency–Inverse Document Frequency

TF-IDF is a classical statistical measure used to quantify how important a
term is to a document relative to a corpus. It was foundational to information
retrieval for decades and remains a useful baseline even in the era of neural
search.

## Term Frequency (TF)

Term frequency measures how often a term appears in a document. The raw count
is often normalized to prevent long documents from having artificially high
scores:

- **Raw count:** `tf(t, d) = count(t in d)`
- **Normalized:** `tf(t, d) = count(t in d) / total_terms(d)`
- **Log normalization:** `tf(t, d) = log(1 + count(t, d))`

The log form is popular because it compresses the dynamic range — a term
appearing 100 times should not be considered 100x more important than one
appearing once.

## Inverse Document Frequency (IDF)

IDF measures how rare a term is across the corpus. Common terms like "the"
or "is" appear in nearly every document and carry little discriminative
information.

```
idf(t) = log(N / df(t))
```

Where `N` is the total number of documents and `df(t)` is the number of
documents containing term `t`. Smoothed variants add 1 to the denominator
to avoid division by zero for unseen terms.

## The Combined Score

```
tfidf(t, d) = tf(t, d) * idf(t)
```

A high TF-IDF score means the term appears frequently in this specific
document but rarely across the corpus — a strong indicator of topic relevance.

## Vectorization

Documents are represented as TF-IDF vectors in a high-dimensional space where
each dimension corresponds to a vocabulary term. Cosine similarity between
these vectors serves as the relevance score for a query.

In practice, the vocabulary dimension is large (tens of thousands of terms),
so TF-IDF vectors are stored as sparse matrices. Scikit-learn's
`TfidfVectorizer` handles this efficiently.

## Limitations Compared to BM25

TF-IDF has two known weaknesses that BM25 addressed:

1. **No TF saturation** — raw TF grows linearly without bound, so documents
   with very high term repetition are disproportionately rewarded.
2. **No length normalization** — longer documents accumulate higher TF counts
   even if their per-unit-length relevance is no better than shorter ones.

BM25 corrects both. However, TF-IDF is still widely used for feature extraction
in machine learning pipelines and as a fast offline baseline.

## Practical Uses in Modern Systems

Despite its age, TF-IDF is still useful for:
- Offline document clustering
- Keyword extraction (terms with high TF-IDF in a document are likely keywords)
- Lightweight search in low-resource environments
- Explainability: TF-IDF scores are easy to interpret compared to neural
  embedding similarity
