"use client";

export function MediaDiscoverySearch({
  searchValue,
  onSearchChange,
  searchLabel,
  placeholder,
  className = "",
}) {
  return (
    <label className={`media-discovery-search${className ? ` ${className}` : ""}`}>
      <span aria-hidden="true">⌕</span>
      <input
        type="search"
        value={searchValue}
        onChange={(event) => onSearchChange(event.target.value)}
        placeholder={placeholder}
        aria-label={searchLabel}
      />
      {searchValue && (
        <button type="button" onClick={() => onSearchChange("")} aria-label="Clear search">
          ×
        </button>
      )}
    </label>
  );
}

export function MediaDiscoveryCategories({ categories, selectedCategory, onSelectCategory }) {
  return (
    <div className="media-discovery-categories" role="group" aria-label="Filter by category">
      {categories.map((category) => (
        <button
          key={category}
          type="button"
          className={`media-category-pill${selectedCategory === category ? " is-active" : ""}`}
          aria-pressed={selectedCategory === category}
          onClick={() => onSelectCategory(category)}
        >
          {category}
        </button>
      ))}
    </div>
  );
}
