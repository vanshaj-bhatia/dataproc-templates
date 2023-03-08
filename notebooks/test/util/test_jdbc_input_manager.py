# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from datetime import datetime
from decimal import Decimal
import pytest
from unittest import mock

from util.jdbc_input_manager import JDBCInputManager
from util.oracle_input_manager import OracleInputManager


ALCHEMY_DB = mock.MagicMock()


def test_input_manager_init():
    for db_type in ["oracle"]:
        mgr = JDBCInputManager.create(db_type, ALCHEMY_DB)
        assert isinstance(mgr, OracleInputManager)


def test__enclose_identifier():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    assert mgr._enclose_identifier('a', "'") == "'a'"
    assert mgr._enclose_identifier('a') == '"a"'
    assert mgr._enclose_identifier('a', '"') == '"a"'
    assert mgr._enclose_identifier('A', '"') == '"A"'


def test_oracle_qualified_name():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    assert mgr._qualified_name('SCHEMA1', 'TABLE1', enclosed=False) == 'SCHEMA1.TABLE1'
    assert mgr._qualified_name('SCHEMA1', 'TABLE1', enclosed=True) == '"SCHEMA1"."TABLE1"'


def test_table_list():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    table_list = ['table1', 'TABLE2']
    mgr.set_table_list(table_list)
    assert mgr.get_table_list() == table_list


def test_get_table_list_with_counts():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    mgr._get_table_count = mock.MagicMock(return_value=42)
    table_list = ['table1', 'table2']
    mgr.set_table_list(table_list)
    assert mgr.get_table_list_with_counts() == [42, 42]


def test__get_count_sql():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    assert isinstance(mgr._get_count_sql('TABLE'), str)


def test__get_max_sql():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    assert isinstance(mgr._get_max_sql('TABLE', 'COLUMN'), str)


def test__get_min_sql():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    assert isinstance(mgr._get_min_sql('TABLE', 'COLUMN'), str)


def test__normalise_oracle_data_type():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    for oracle_type, normalised_type in [
        ('DATE', 'DATE'),
        ('TIMESTAMP(0)', 'TIMESTAMP'),
        ('TIMESTAMP(3) WITH TIME ZONE', 'TIMESTAMP WITH TIME ZONE'),
        ('TIMESTAMP(6) WITH LOCAL TIME ZONE', 'TIMESTAMP WITH LOCAL TIME ZONE'),
        ('INTERVAL DAY(5) TO SECOND(1)', 'INTERVAL DAY TO SECOND'),
    ]:
        assert mgr._normalise_oracle_data_type(oracle_type) == normalised_type


def test__read_partitioning_num_partitions():
    mgr = JDBCInputManager.create("oracle", ALCHEMY_DB)
    # Numeric ranges
    for lowerbound, upperbound, stride, expected_partitions in [
        [1, 100, 10, 10],
        [float(1), float(100), float(10), 10],
        [Decimal(1), Decimal(100), Decimal(10), 10],
        [int(1), float(100), Decimal(10), 10],
        [Decimal(1), Decimal(9_999_999_999_999_999_999), Decimal(1_000_000_000_000_000_000), 10],
        [1, 105, 10, 11],
        [-99, 1, 10, 10],
    ]:
        assert mgr._read_partitioning_num_partitions(lowerbound, upperbound, stride) == expected_partitions

    # Datetime ranges are currently unsupported
    for lowerbound, upperbound, stride, expected_partitions in [
        [datetime(2020, 1, 1), datetime(2020, 1, 20), 2, 10],
    ]:
        with pytest.raises(NotImplementedError):
            assert mgr._read_partitioning_num_partitions(lowerbound, upperbound, stride) == expected_partitions
