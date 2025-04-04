# core/shopify_graphql/queries.py

GET_COLLECTIONS_QUERY = """
query getCollections($first: Int!) {
  collections(first: $first) {
    edges {
      node {
        id
        legacyResourceId
        title
        handle
      }
    }
  }
}
"""

GET_COLLECTIONS_QUERY_PAGINATED = """
query getCollections($first: Int!, $after: String) {
  collections(first: $first, after: $after) {
    edges {
      node {
        id
        legacyResourceId
        title
        handle
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""
