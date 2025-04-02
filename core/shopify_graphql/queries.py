# core/shopify_graphql/queries.py

GET_COLLECTIONS_QUERY = """
query getCollections($first: Int!) {
  collections(first: $first) {
    edges {
      node {
        id
        title
        handle
      }
    }
  }
}
"""