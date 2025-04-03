PRODUCT_CREATE_MUTATION = """
mutation productCreate($input: ProductInput!) {
  productCreate(input: $input) {
    product {
      id
      legacyResourceId
      handle
      variants(first: 1) {
        edges {
          node {
            id
          }
        }
      }
    }
    userErrors {
      field
      message
    }
  }
}
"""

PRODUCT_VARIANTS_BULK_UPDATE_MUTATION = """
mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants {
      id
      title
      price
    }
    userErrors {
      field
      message
    }
  }
}
"""


STAGED_UPLOADS_CREATE_MUTATION = """
mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets {
      url
      resourceUrl
      parameters {
        name
        value
      }
    }
    userErrors {
      field
      message
    }
  }
}
"""

COLLECTION_ADD_PRODUCTS_MUTATION = """
mutation collectionAddProducts($id: ID!, $productIds: [ID!]!) {
  collectionAddProducts(id: $id, productIds: $productIds) {
    collection {
      id
      title
    }
    userErrors {
      field
      message
    }
  }
}
"""

COLLECTION_CREATE_MUTATION = """
mutation collectionCreate($input: CollectionInput!) {
  collectionCreate(input: $input) {
    collection {
      id
      legacyResourceId
      title
      handle
    }
    userErrors {
      field
      message
    }
  }
}
"""

PRODUCT_IMAGES_ATTACH_MUTATION = """
mutation productUpdateImages($productId: ID!, $images: [ImageInput!]!) {
  productUpdateImages(productId: $productId, images: $images) {
    product {
      images(first: 10) {
        edges {
          node {
            id
            originalSrc
          }
        }
      }
    }
    userErrors {
      field
      message
    }
  }
}
"""