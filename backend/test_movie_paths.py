"""Movie path checker regression tests; no filesystem or Jellyfin access."""
import copy
import unittest
from unittest.mock import patch

from media import normalize_items
from movie_paths import analyze_movies, CATEGORY_ORDER, classify_row, row_needs_stdout


def classify(title='The Matrix', year='1999', folder=None, filename=None):
    component = f'{title} ({year})'
    path = f'/home/jellyfin/media/movies/{folder or component}/{filename or component}.mkv'
    return classify_row({'title': title, 'year': year, 'path': path}, 92)


class MatchingTests(unittest.TestCase):
    def test_exact_names_and_valid_version_tag(self):
        result = classify(filename='The Matrix (1999) - [1080p HEVC]')
        self.assertEqual(result['category'], CATEGORY_ORDER[0])
        self.assertTrue(result['folder_file_exact_match'])
        self.assertFalse(row_needs_stdout(result))

    def test_case_and_symbols_have_separate_categories(self):
        self.assertEqual(classify(folder='the matrix (1999)', filename='the matrix (1999)')['category'], CATEGORY_ORDER[1])
        self.assertEqual(classify(title='WALL·E', year='2008', folder='WALL-E (2008)', filename='WALL-E (2008)')['category'], CATEGORY_ORDER[2])

    def test_year_differences(self):
        for year, category in [('1998', CATEGORY_ORDER[3]), ('1997', CATEGORY_ORDER[4])]:
            with self.subTest(year=year):
                result = classify(folder=f'The Matrix ({year})', filename=f'The Matrix ({year})')
                self.assertEqual(result['category'], category)
                self.assertEqual(result['folder_year_delta'], 1999 - int(year))

    def test_spelling_and_possible_misidentification(self):
        self.assertEqual(classify(title='The Shawshank Redemption', year='1994', folder='The Shawshank Redemtion (1994)', filename='The Shawshank Redemtion (1994)')['category'], CATEGORY_ORDER[5])
        self.assertEqual(classify(folder='Alien (1979)', filename='Alien (1979)')['category'], CATEGORY_ORDER[6])

    def test_title_variants_and_subtitles_are_preserved(self):
        for title, actual in [('Rocky II', 'Rocky 2'), ('Fast & Furious', 'Fast and Furious'),
                              ('Amélie', 'Amelie'), ('Star Trek: First Contact', 'Star Trek')]:
            with self.subTest(title=title):
                result = classify(title=title, year='2000', folder=actual + ' (2000)', filename=actual + ' (2000)')
                self.assertNotEqual(result['category'], CATEGORY_ORDER[6])
                self.assertEqual(result['best_title_similarity'], 100)
        self.assertIn('colon-trimmed', classify(title='Star Trek: First Contact', year='2000', folder='Star Trek (2000)', filename='Star Trek (2000)')['notes'])

    def test_misplaced_version_tags_are_independent_of_category(self):
        result = classify(folder='The Matrix Extended and Remastered (1999)', filename='The Matrix Extended and Remastered (1999)')
        self.assertEqual(result['category'], CATEGORY_ORDER[0])
        self.assertTrue(result['incorrectly_formatted_version_tag'])
        self.assertEqual(result['folder_removed_version_tags'], ['Extended', 'Remastered'])
        self.assertTrue(row_needs_stdout(result))

    def test_overall_category_uses_better_side_but_difference_still_flagged(self):
        result = classify(filename='A Completely Different Movie (2000)')
        self.assertEqual(result['category'], CATEGORY_ORDER[0])
        self.assertEqual(result['bucket_source'], 'folder')
        self.assertEqual(result['file_category'], CATEGORY_ORDER[6])
        self.assertFalse(result['folder_file_exact_match'])
        self.assertTrue(row_needs_stdout(result))


class ReportTests(unittest.TestCase):
    def normalized_movies(self):
        item = {'Id': 'movie', 'Name': 'The Matrix', 'ProductionYear': 1999, 'Type': 'Movie', 'LocationType': 'FileSystem', 'MediaSources': [
            {'Id': 'standard', 'Path': '/home/jellyfin/media/movies/The Matrix (1999)/The Matrix (1999).mkv'},
            {'Id': 'extended', 'Name': 'Extended', 'Path': '/home/jellyfin/media/movies/The Matrix (1999)/The Matrix Extended (1999).mkv'},
        ]}
        rows, _ = normalize_items([item], [])
        return rows

    def test_all_versions_checked_and_episodes_excluded(self):
        rows = self.normalized_movies()
        episode = {**rows[0], 'id': 'episode', 'type': 'Episode'}
        with patch('builtins.open', side_effect=AssertionError('The checker must not access media files.')):
            report = analyze_movies(rows + [episode])
        self.assertEqual(report['summary']['total_movies'], 2)
        self.assertEqual(report['summary']['checked'], 2)
        self.assertEqual(report['summary']['needs_review'], 1)
        self.assertEqual(report['summary']['bad_version_tags'], 1)
        self.assertEqual(report['rows'][1]['version_name'], 'Extended')
        self.assertEqual(sum(item['count'] for item in report['summary']['categories']), 2)

    def test_missing_title_year_and_path_are_explicitly_uncheckable(self):
        for field in ['metadata_title', 'production_year', 'path']:
            with self.subTest(field=field):
                row = {**self.normalized_movies()[0], field: None}
                report = analyze_movies([row])
                self.assertEqual(report['summary']['uncheckable'], 1)
                self.assertEqual(report['summary']['checked'], 0)
                self.assertEqual(report['rows'][0]['status'], 'uncheckable')
                self.assertNotIn('category', report['rows'][0])
                self.assertTrue(report['rows'][0]['needs_review'])

    def test_metadata_year_is_normalized_to_a_valid_integer(self):
        base = {'Id': 'movie', 'Name': 'Film', 'Type': 'Movie', 'LocationType': 'FileSystem', 'MediaSources': [{}]}
        for value in [None, 0, True, 1999.5, '1999', 10000]:
            with self.subTest(value=value):
                rows, _ = normalize_items([{**base, 'ProductionYear': value}], [])
                self.assertIsNone(rows[0]['production_year'])
        rows, _ = normalize_items([{**base, 'ProductionYear': 1999}], [])
        self.assertEqual(rows[0]['production_year'], 1999)

    def test_empty_report_and_input_immutability(self):
        self.assertEqual(analyze_movies([])['summary']['total_movies'], 0)
        rows = self.normalized_movies()
        original = copy.deepcopy(rows)
        analyze_movies(rows, 95)
        self.assertEqual(rows, original)


if __name__ == '__main__':
    unittest.main()
