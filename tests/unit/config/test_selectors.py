import textwrap
import unittest

import pytest
import yaml

import dbt.exceptions
from dbt.config.selectors import (
    SelectorConfig,
    SelectorDict,
    selector_config_from_data,
    selector_data_from_root,
)
from dbt.contracts.selection import SelectorFile


def get_selector_dict(txt: str) -> dict:
    txt = textwrap.dedent(txt)
    dct = yaml.safe_load(txt)
    return dct


class TestSelectorMeta:
    def test_meta_is_parsed(self):
        dct = get_selector_dict(
            """\
            selectors:
              - name: with_meta
                meta:
                  owner: analytics
                definition: tag:nightly
            """
        )
        assert SelectorFile.from_dict(dct).selectors[0].meta == {"owner": "analytics"}
        assert isinstance(selector_config_from_data(dct), SelectorConfig)

    def test_meta_defaults_to_empty_dict(self):
        dct = get_selector_dict(
            """\
            selectors:
              - name: without_meta
                definition: tag:nightly
            """
        )
        assert SelectorFile.from_dict(dct).selectors[0].meta == {}


class TestSelectorDataFromRoot:
    """Selectors are read from every `selectors/selectors*.yml` file of the project."""

    @staticmethod
    def _write_selectors(root, file_name: str, *selector_names: str) -> None:
        selectors_dir = root / "selectors"
        selectors_dir.mkdir(exist_ok=True)
        lines = ["selectors:"]
        for name in selector_names:
            lines += [f"  - name: {name}", f"    definition: tag:{name}"]
        (selectors_dir / file_name).write_text("\n".join(lines) + "\n")

    def test_no_selector_files_returns_none(self, tmp_path):
        assert selector_data_from_root(str(tmp_path)) is None

    def test_selectors_from_multiple_files_are_merged(self, tmp_path):
        self._write_selectors(tmp_path, "selectors_a.yml", "alpha")
        self._write_selectors(tmp_path, "selectors_b.yml", "beta", "gamma")

        data = selector_data_from_root(str(tmp_path))

        assert sorted(s["name"] for s in data["selectors"]) == ["alpha", "beta", "gamma"]

    def test_duplicate_selector_names_across_files_raise(self, tmp_path):
        self._write_selectors(tmp_path, "selectors_a.yml", "alpha")
        self._write_selectors(tmp_path, "selectors_b.yml", "alpha")

        with pytest.raises(dbt.exceptions.SelectorsParsingError, match="alpha"):
            selector_data_from_root(str(tmp_path))

    def test_root_level_selectors_yml_is_not_read(self, tmp_path):
        (tmp_path / "selectors.yml").write_text(
            "selectors:\n  - name: legacy\n    definition: tag:legacy\n"
        )

        assert selector_data_from_root(str(tmp_path)) is None


class SelectorUnitTest(unittest.TestCase):
    def test_parse_multiple_excludes(self):
        dct = get_selector_dict(
            """\
            selectors:
                - name: mult_excl
                  definition:
                    union:
                      - method: tag
                        value: nightly
                      - exclude:
                         - method: tag
                           value: hourly
                      - exclude:
                         - method: tag
                           value: daily
            """
        )
        with self.assertRaisesRegex(
            dbt.exceptions.DbtSelectorsError, "cannot provide multiple exclude arguments"
        ):
            selector_config_from_data(dct)

    def test_parse_set_op_plus(self):
        dct = get_selector_dict(
            """\
            selectors:
                - name: union_plus
                  definition:
                    - union:
                       - method: tag
                         value: nightly
                       - exclude:
                          - method: tag
                            value: hourly
                    - method: tag
                      value: foo
            """
        )
        with self.assertRaisesRegex(
            dbt.exceptions.DbtSelectorsError, "Valid root-level selector definitions"
        ):
            selector_config_from_data(dct)

    def test_parse_multiple_methods(self):
        dct = get_selector_dict(
            """\
            selectors:
                - name: mult_methods
                  definition:
                    - tag:hourly
                    - tag:nightly
                    - fqn:start
            """
        )
        with self.assertRaisesRegex(
            dbt.exceptions.DbtSelectorsError, "Valid root-level selector definitions"
        ):
            selector_config_from_data(dct)

    def test_parse_set_with_method(self):
        dct = get_selector_dict(
            """\
                selectors:
                  - name: mixed_syntaxes
                    definition:
                      key: value
                      method: tag
                      value: foo
                      union:
                        - method: tag
                          value: m1234
                        - exclude:
                          - method: tag
                            value: m5678
            """
        )
        with self.assertRaisesRegex(
            dbt.exceptions.DbtSelectorsError,
            "Only a single 'union' or 'intersection' key is allowed",
        ):
            selector_config_from_data(dct)

    def test_complex_sector(self):
        dct = get_selector_dict(
            """\
                selectors:
                  - name: nightly_diet_snowplow
                    definition:
                      union:
                        - intersection:
                            - method: source
                              value: snowplow
                              childrens_parents: true
                            - method: tag
                              value: nightly
                        - method: path
                          value: models/export
                        - exclude:
                            - intersection:
                                - method: package
                                  value: snowplow
                                - method: config.materialized
                                  value: incremental
                            - method: fqn
                              value: export_performance_timing
            """
        )
        selectors = selector_config_from_data(dct)
        assert isinstance(selectors, SelectorConfig)

    def test_exclude_not_list(self):
        dct = get_selector_dict(
            """\
                selectors:
                  - name: summa_exclude
                    definition:
                      union:
                        - method: tag
                          value: nightly
                        - exclude:
                            method: tag
                            value: daily
            """
        )
        with self.assertRaisesRegex(dbt.exceptions.DbtSelectorsError, "Expected a list"):
            selector_config_from_data(dct)

    def test_invalid_key(self):
        dct = get_selector_dict(
            """\
                selectors:
                  - name: summa_nothing
                    definition:
                      method: tag
                      key: nightly
            """
        )
        with self.assertRaisesRegex(dbt.exceptions.DbtSelectorsError, "Expected either 1 key"):
            selector_config_from_data(dct)

    def test_invalid_single_def(self):
        dct = get_selector_dict(
            """\
                selectors:
                  - name: summa_nothing
                    definition:
                      fubar: tag
            """
        )
        with self.assertRaisesRegex(dbt.exceptions.DbtSelectorsError, "not a valid method name"):
            selector_config_from_data(dct)

    def test_method_no_value(self):
        dct = get_selector_dict(
            """\
                selectors:
                  - name: summa_nothing
                    definition:
                      method: tag
            """
        )
        with self.assertRaisesRegex(dbt.exceptions.DbtSelectorsError, "not a valid method name"):
            selector_config_from_data(dct)

    def test_multiple_default_true(self):
        """Test selector_config_from_data returns the correct error when multiple
        default values are set
        """
        dct = get_selector_dict(
            """\
                selectors:
                  - name: summa_nothing
                    definition:
                      method: tag
                      value: nightly
                    default: true
                  - name: summa_something
                    definition:
                      method: tag
                      value: daily
                    default: true
        """
        )
        with self.assertRaisesRegex(
            dbt.exceptions.DbtSelectorsError, "Found multiple selectors with `default: true`:"
        ):
            selector_config_from_data(dct)

    def test_compare_cli_non_cli(self):
        dct = get_selector_dict(
            """\
            selectors:
              - name: nightly_diet_snowplow
                description: "This uses more CLI-style syntax"
                definition:
                  union:
                    - intersection:
                        - '@source:snowplow'
                        - 'tag:nightly'
                    - 'models/export'
                    - exclude:
                        - intersection:
                            - 'package:snowplow'
                            - 'config.materialized:incremental'
                        - export_performance_timing
              - name: nightly_diet_snowplow_full
                description: "This is a fuller YAML specification"
                definition:
                  union:
                    - intersection:
                        - method: source
                          value: snowplow
                          childrens_parents: true
                        - method: tag
                          value: nightly
                    - method: path
                      value: models/export
                    - exclude:
                        - intersection:
                            - method: package
                              value: snowplow
                            - method: config.materialized
                              value: incremental
                        - method: fqn
                          value: export_performance_timing
            """
        )

        sel_dict = SelectorDict.parse_from_selectors_list(dct["selectors"])
        assert sel_dict
        with_strings = sel_dict["nightly_diet_snowplow"]["definition"]
        no_strings = sel_dict["nightly_diet_snowplow_full"]["definition"]
        self.assertEqual(with_strings, no_strings)

    def test_single_string_definition(self):
        dct = get_selector_dict(
            """\
            selectors:
              - name: nightly_selector
                definition:
                  'tag:nightly'
            """
        )

        sel_dict = SelectorDict.parse_from_selectors_list(dct["selectors"])
        assert sel_dict
        expected = {"method": "tag", "value": "nightly"}
        definition = sel_dict["nightly_selector"]["definition"]
        self.assertEqual(expected, definition)

    def test_single_key_value_definition(self):
        dct = get_selector_dict(
            """\
            selectors:
              - name: nightly_selector
                definition:
                  tag: nightly
            """
        )

        sel_dict = SelectorDict.parse_from_selectors_list(dct["selectors"])
        assert sel_dict
        expected = {"method": "tag", "value": "nightly"}
        definition = sel_dict["nightly_selector"]["definition"]
        self.assertEqual(expected, definition)

    def test_parent_definition(self):
        dct = get_selector_dict(
            """\
            selectors:
              - name: kpi_nightly_selector
                definition:
                  '+exposure:kpi_nightly'
            """
        )

        sel_dict = SelectorDict.parse_from_selectors_list(dct["selectors"])
        assert sel_dict
        expected = {"method": "exposure", "value": "kpi_nightly", "parents": True}
        definition = sel_dict["kpi_nightly_selector"]["definition"]
        self.assertEqual(expected, definition)

    def test_plus_definition(self):
        dct = get_selector_dict(
            """\
            selectors:
              - name: my_model_children_selector
                definition:
                  'my_model+2'
            """
        )

        sel_dict = SelectorDict.parse_from_selectors_list(dct["selectors"])
        assert sel_dict
        expected = {"method": "fqn", "value": "my_model", "children": True, "children_depth": "2"}
        definition = sel_dict["my_model_children_selector"]["definition"]
        self.assertEqual(expected, definition)
