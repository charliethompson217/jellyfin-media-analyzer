export const PATH_CATEGORIES = [
  ['everything matches exactly', 'Exact match'],
  ['ignoring case, everything matches exactly', 'Case differences'],
  ['ignoring symbols and case, everything matches exactly', 'Symbol / case differences'],
  ['ignoring symbols and case, year is the only thing wrong (off by 1)', 'Year differs by 1'],
  ['ignoring symbols and case, year is the only thing wrong (off by more than 1)', 'Year differs by more than 1'],
  ['some issue like spelling', 'Possible spelling issue'],
  ['possible misidentified', 'Possibly misidentified'],
];
export const categoryLabel = category => PATH_CATEGORIES.find(([key]) => key === category)?.[1] || 'Not checked';

export function filterPathResults(rows, { search = '', category = '', flag = '', issuesOnly = true }) {
  const term = search.trim().toLowerCase();
  return rows.filter(row =>
    (!issuesOnly || row.needs_review) &&
    (!category || row.category === category) &&
    (!flag || (flag === 'folder' ? row.status === 'checked' && !row.folder_file_exact_match
      : flag === 'version' ? row.incorrectly_formatted_version_tag : row.status === 'uncheckable')) &&
    (!term || [row.title, row.year, row.path, row.expected_component, row.notes, row.version_name]
      .some(value => String(value ?? '').toLowerCase().includes(term))),
  );
}

export const PATH_EXPORT_COLUMNS = [
  ['title', 'Title'], ['year', 'Year'], ['version_name', 'Version'], ['path', 'Jellyfin Path'],
  ['status', 'Check Status'], ['uncheckable_reason', 'Not Checked Reason'], ['needs_review', 'Needs Review'],
  ['expected_component', 'Expected Title and Year'], ['category', 'Overall Category'], ['bucket_source', 'Best Match Source'],
  ['best_title_similarity', 'Best Title Similarity (%)'], ['folder_file_exact_match', 'Folder/File Exact Match'],
  ['incorrectly_formatted_version_tag', 'Incorrect Version Tag'], ['folder_component', 'Folder'], ['file_component', 'Filename Without Version'],
  ['folder_cleaned_component', 'Folder Used for Match'], ['file_cleaned_component', 'Filename Used for Match'],
  ['folder_category', 'Folder Category'], ['file_category', 'Filename Category'],
  ['folder_year_matches_metadata', 'Folder Year Matches'], ['file_year_matches_metadata', 'Filename Year Matches'],
  ['folder_incorrectly_formatted_version_tag', 'Folder Version Tag Issue'], ['file_incorrectly_formatted_version_tag', 'Filename Version Tag Issue'],
  ['folder_year_delta', 'Folder Year Delta'], ['file_year_delta', 'Filename Year Delta'],
  ['folder_title_similarity', 'Folder Similarity (%)'], ['file_title_similarity', 'Filename Similarity (%)'],
  ['folder_removed_version_tags', 'Folder Removed Tags'], ['file_removed_version_tags', 'Filename Removed Tags'],
  ['folder_best_variant_pair', 'Folder Match Variants'], ['file_best_variant_pair', 'Filename Match Variants'], ['notes', 'Notes'],
].map(([accessorKey, header]) => ({ accessorKey, header }));

export function pathExportRows(rows) {
  return rows.map(row => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, Array.isArray(value) ? value.join(' | ') : value])));
}
