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

import re
from textwrap import dedent
from typing import List, Optional, Tuple, TYPE_CHECKING

from util.jdbc.jdbc_input_manager_interface import (
    JDBCInputManagerInterface,
    JDBCInputManagerException,
    SPARK_PARTITION_COLUMN,
    SPARK_NUM_PARTITIONS,
    SPARK_LOWER_BOUND,
    SPARK_UPPER_BOUND,
    PARTITION_COMMENT,
)

if TYPE_CHECKING:
    import sqlalchemy


class OracleInputManager(JDBCInputManagerInterface):
    # Private methods

    def _build_table_list(
        self,
        schema_filter: Optional[str] = None,
        table_filter: Optional[List[str]] = None,
    ) -> Tuple[str, List[str]]:
        """
        Return a tuple containing schema and list of table names based on optional schema/table filters.
        If schema_filter is not provided then the connected user is used for the schema.
        """
        with self._alchemy_db.connect() as conn:
            schema = self._normalise_schema_filter(schema_filter, conn)
            not_like_filter = "table_name NOT LIKE 'DR$SUP_TEXT_IDX%'"
            if schema_filter:
                sql = f"SELECT table_name FROM all_tables WHERE owner = :own AND {not_like_filter}"
                rows = conn.execute(sql, own=schema).fetchall()
            else:
                sql = f"SELECT table_name FROM user_tables WHERE {not_like_filter}"
                rows = conn.execute(sql).fetchall()
            tables = [_[0] for _ in rows] if rows else rows
            return schema, self._filter_table_list(tables, table_filter)

    def _define_read_partitioning(
        self,
        table: str,
        row_count_threshold: int,
        sa_connection: "sqlalchemy.engine.base.Connection",
    ) -> str:
        """Return a dictionary defining how to partition the Spark SQL extraction."""
        # TODO In the future we may want to support checking DBA_SEGMENTS
        row_count = self._get_table_count(table, sa_connection=sa_connection)
        if row_count > int(row_count_threshold):
            # The table has enough rows to merit partitioning Spark SQL read.
            # TODO Prioritise partition keys over primary keys in the future.
            # TODO Add support for UKs alongside PKs.
            if self.get_primary_keys().get(table):
                # This code takes the first column from the PK, this could be flawed
                # if the primary key is composite and the first column is not distinct.
                column = self.get_primary_keys().get(table)[0]
                column_datatype = self._get_column_data_type(table, column)
                if column_datatype == "NUMBER":
                    lowerbound = sa_connection.execute(
                        self._get_min_sql(table, column)
                    ).fetchone()
                    upperbound = sa_connection.execute(
                        self._get_max_sql(table, column)
                    ).fetchone()
                    if lowerbound and upperbound:
                        lowerbound = lowerbound[0]
                        upperbound = upperbound[0]
                        num_partitions = self._read_partitioning_num_partitions(
                            lowerbound, upperbound, row_count_threshold
                        )
                        return {
                            SPARK_PARTITION_COLUMN: column,
                            SPARK_NUM_PARTITIONS: num_partitions,
                            SPARK_LOWER_BOUND: lowerbound,
                            SPARK_UPPER_BOUND: upperbound,
                            PARTITION_COMMENT: f"Partitioning by {column_datatype} primary key column",
                        }
        return None

    def _enclose_identifier(self, identifier, ch: Optional[str] = None):
        """Enclose an identifier in the standard way for the SQL engine."""
        ch = ch or '"'
        return f"{ch}{identifier}{ch}"

    def _get_column_data_type(
        self,
        table: str,
        column: str,
        sa_connection: "Optional[sqlalchemy.engine.base.Connection]" = None,
    ) -> str:
        sql = dedent(
            """
        SELECT data_type
        FROM   all_tab_columns
        WHERE  owner = :own
        AND    table_name = :tab
        AND    column_name = :col
        """
        )
        if sa_connection:
            row = sa_connection.execute(
                sql, own=self._schema, tab=table, col=column
            ).fetchone()
        else:
            with self._alchemy_db.connect() as conn:
                row = conn.execute(
                    sql, own=self._schema, tab=table, col=column
                ).fetchone()
        return self._normalise_oracle_data_type(row[0]) if row else row

    def _get_primary_keys(self) -> dict:
        """
        Return a dict of primary key information.
        The dict is keyed on table name and maps to a list of column names.
        """
        pk_dict = {_: None for _ in self._table_list}
        sql = dedent(
            """
        SELECT cols.column_name
        FROM   all_constraints cons
        ,      all_cons_columns cols
        WHERE  cons.owner = :own
        AND    cons.table_name = :tab
        AND    cons.constraint_type = 'P'
        AND    cons.status = 'ENABLED'
        AND    cols.constraint_name = cons.constraint_name
        AND    cols.owner = cons.owner
        AND    cols.table_name = cons.table_name
        ORDER BY cols.position
        """
        )
        with self._alchemy_db.connect() as conn:
            for table in self._table_list:
                rows = conn.execute(sql, own=self._schema, tab=table).fetchall()
                if rows:
                    pk_dict[table] = [_[0] for _ in rows]
            return pk_dict

    def _normalise_oracle_data_type(self, data_type: str) -> str:
        """Oracle TIMESTAMP types are polluted with scale, this method strips that noise away."""
        if data_type.startswith("TIMESTAMP") or data_type.startswith("INTERVAL DAY"):
            return re.sub(r"\([0-9]\)", r"", data_type)
        else:
            return data_type

    def _normalise_schema_filter(
        self, schema_filter: str, sa_connection: "sqlalchemy.engine.base.Connection"
    ) -> str:
        """Return schema_filter normalised to the correct case, or sets to connected user if blank."""
        if schema_filter:
            # Assuming there will not be multiple schemas of the same name in different case.
            sql = "SELECT username FROM all_users WHERE UPPER(username) = UPPER(:b1) ORDER BY username"
            row = sa_connection.execute(sql, b1=schema_filter).fetchone()
            if not row:
                raise JDBCInputManagerException(
                    f"Schema filter does not match any Oracle schemas: {schema_filter}"
                )
        else:
            sql = "SELECT USER FROM dual"
            row = sa_connection.execute(sql).fetchone()
        return row[0] if row else row

    def _qualified_name(self, schema: str, table: str, enclosed=False) -> str:
        if enclosed:
            return (
                self._enclose_identifier(schema, '"')
                + "."
                + self._enclose_identifier(table, '"')
            )
        else:
            return schema + "." + table

    # Public methods
