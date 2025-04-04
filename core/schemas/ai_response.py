from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class ProductType(str, Enum):
    Protein_Powder = "Protein Powder"
    Protein_Bar = "Protein Bar"
    Protein_Snack = "Protein Snack"
    Pre_Workout = "Pre Workout"
    Intra_Workout = "Intra Workout"
    Post_Workout = "Post Workout"
    Creatine = "Creatine"
    BCAA = "BCAA"
    EAA = "EAA"
    Mass_Gainer = "Mass Gainer"
    Weight_Loss = "Weight Loss"
    Vegan_Supplement = "Vegan Supplement"
    Low_Calorie_Treat = "Low Calorie Treat"
    Hydration = "Hydration"
    Vitamin = "Vitamin"
    Mineral = "Mineral"
    Health_Supplement = "Health Supplement"
    Clothing = "Clothing"
    Meal_Replacement = "Meal Replacement"
    Energy_Supplement = "Energy Supplement"
    Superfood = "Superfood"
    Nut_Butter = "Nut Butter"
    Accessory = "Accessory"

class PrimaryCollection(str, Enum):
    Protein_Powders = "Protein Powders"
    Protein_Bars = "Protein Bars"
    Protein_Snacks = "Protein Snacks"
    Pre_Workout = "Pre Workout"
    Intra_Workout = "Intra Workout"
    Post_Workout = "Post Workout"
    Creatine = "Creatine"
    BCAA = "BCAA"
    EAA = "EAA"
    Mass_Gainers = "Mass Gainers"
    Weight_Loss = "Weight Loss"
    Vegan_Supplements = "Vegan Supplements"
    Low_Calorie_Treats = "Low Calorie Treats"
    Hydration = "Hydration"
    Vitamins = "Vitamins"
    Minerals = "Minerals"
    Health_Supplements = "Health Supplements"
    Clothing = "Clothing"
    Meal_Replacements = "Meal Replacements"
    Energy_Supplements = "Energy Supplements"
    Superfoods = "Superfoods"
    Nut_Butters = "Nut Butters"
    Accessories = "Accessories"

class NutritionalFact(BaseModel):
    type: str = Field(
        ..., title="Type",
        description="The type of nutritional information we are detailing eg. calories, protein, carbs, sugar, salt, serving size, servings per container etc"
    )
    amount: float = Field(
        ..., title="Amount",
        description="The numerical amount of this type of nutritional content"
    )
    unit: str = Field(
        ..., title="Unit",
        description="If applicable, the measurement unit of this nutritional content eg. grams, mg, ml etc"
    )

class AIResponse(BaseModel):
    title: str = Field(
        ..., title="Title",
        description="The main product title, this must include the product brand, type of product as well as its name and any other important details like packaging size"
    )
    description: str = Field(
        ..., title="Description",
        description="HTML formatted full product description including all required structure and bullet points. You must not mention expiry date, this description needs to be relevant regardless of date"
    )
    snippet: str = Field(
        ..., title="Snippet",
        description="A short, snappy summary of the product suitable for use on landing pages"
    )
    product_type: ProductType = Field(
        ..., title="Product Type",
        description="Categorisation of the product from the available enums"
    )
    primary_collection: PrimaryCollection = Field(
        ..., title="Primary Collection",
        description="The main Shopify collection for this product"
    )
    secondary_collections: Optional[List[str]] = Field(
        None, title="Secondary Collections",
        description="Additional Shopify collections this product may belong to"
    )
    suggested_use: Optional[str] = Field(
        None, title="Suggested Use",
        description="How the product should be used or consumed, if known"
    )
    ingredients: Optional[List[str]] = Field(
        None, title="Ingredients",
        description="A list of ingredients used in the product, if available"
    )
    nutritional_facts: Optional[List[NutritionalFact]] = Field(
        None, title="Nutritional Facts",
        description="Structured nutritional values like protein, calories, carbs etc"
    )
    tags: List[str] = Field(
        ..., title="Tags",
        description="Lowercase or slug-formatted Shopify tags for admin use, such as brand, product type, and related search terms"
    )
    seo_title: str = Field(
        ..., title="SEO Title",
        description="Meta title for search engines, max 60 characters"
    )
    seo_description: str = Field(
        ..., title="SEO Description",
        description="Meta description for search engines, max 160 characters"
    )
    seo_keywords: Optional[List[str]] = Field(
        None, title="SEO Keywords",
        description="Optional meta keywords to improve search visibility"
    )
