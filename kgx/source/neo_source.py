import itertools
from typing import Any, Dict, List, Optional, Iterator, Tuple

import click
from neo4jrestclient.client import GraphDatabase
from neo4jrestclient.query import CypherException

from kgx.config import get_logger
from kgx.source.source import Source
from neo4jrestclient.client import GraphDatabase, Node, Relationship, GraphDatabase

from kgx.utils.kgx_utils import generate_uuid, generate_edge_key

log = get_logger()


class NeoSource(Source):
    def __init__(self):
        super().__init__()
        self.node_count = 0
        self.edge_count = 0
        self.seen_nodes = set()

    def parse(self, uri, username, password, start = 0, end = None, is_directed = True, page_size = 50000, provided_by = None):
        self.http_driver: GraphDatabase = GraphDatabase(uri, username=username, password=password)
        if provided_by:
            self.graph_metadata['provided_by'] = [provided_by]
        kwargs = {'is_directed': is_directed}
        for page in self.get_pages(self.get_nodes, start, end, page_size=page_size, **kwargs):
            yield from self.load_nodes(page)
        for page in self.get_pages(self.get_edges, start, end, page_size=page_size, **kwargs):
            yield from self.load_edges(page)

    def count(self, is_directed: bool = True) -> int:
        """
        Get the total count of records to be fetched from the Neo4j database.

        Parameters
        ----------
        is_directed: bool
            Are edges directed or undirected (``True``, by default, since edges in most cases are directed)

        Returns
        -------
        int
            The total count of records

        """
        direction = '->' if is_directed else '-'
        query = f"MATCH (s)-[p]{direction}(o)"

        if self.edge_filters:
            qs = []
            if 'subject_category' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('subject_category', 's', ':', 'OR')})")
            if 'object_category' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('object_category', 'o', ':', 'OR')})")
            if 'predicate' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('predicate', 'p', '.')})")
            if 'provided_by' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('provided_by', 'p', '.', 'OR')})")
            query = ' WHERE '
            query += ' AND '.join(qs)
        query += f" RETURN COUNT(*) AS count"
        log.debug(query)
        query_result: Any
        counts: int = 0
        try:
            query_result = self.http_driver.query(query)
            for result in query_result:
                counts = result[0]
        except CypherException as ce:
            log.error(ce)
        return counts

    def get_nodes(self, skip: int = 0, limit: int = 0, **kwargs) -> List:
        """
        Get a page of nodes from the Neo4j database.

        Parameters
        ----------
        skip: int
            Records to skip
        limit: int
            Total number of records to query for

        Returns
        -------
        list
            A list of nodes

        """
        query = f"MATCH (n)"

        if self.node_filters:
            qs = []
            if 'category' in self.node_filters:
                qs.append(f"({self.get_node_filter('category', 'n', ':', 'OR')})")
            if 'provided_by' in self.node_filters:
                qs.append(f"({self.get_node_filter('provided_by', 'n', '.', 'OR')})")
            query += ' WHERE '
            query += ' AND '.join(qs)

        query += f" RETURN n SKIP {skip}"

        if limit:
            query += f" LIMIT {limit}"

        log.debug(query)
        nodes = []
        try:
            results = self.http_driver.query(query, returns=Node, data_contents=True)
            if results:
                nodes = [node[0] for node in results.rows]
        except CypherException as ce:
            log.error(ce)
        return nodes

    def get_edges(self, skip: int = 0, limit: int = 0, is_directed: bool = True, **kwargs) -> List:
        """
        Get a page of edges from the Neo4j database.

        Parameters
        ----------
        skip: int
            Records to skip
        limit: int
            Total number of records to query for
        is_directed: bool
            Are edges directed or undirected (``True``, by default, since edges in most cases are directed)

        Returns
        -------
        list
            A list of 3-tuples

        """
        direction = '->' if is_directed else '-'
        query = f"MATCH (s)-[p]{direction}(o)"

        if self.edge_filters:
            qs = []
            if 'subject_category' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('subject_category', 's', ':', 'OR')})")
            if 'object_category' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('object_category', 'o', ':', 'OR')})")
            if 'predicate' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('predicate', 'p', '.')})")
            if 'provided_by' in self.edge_filters:
                qs.append(f"({self.get_edge_filter('provided_by', 'p', '.', 'OR')})")
            query += ' WHERE '
            query += ' AND '.join(qs)
        query += f" RETURN s, p, o SKIP {skip}"

        if limit:
            query += f" LIMIT {limit}"

        log.debug(query)
        edges = []
        try:
            results = self.http_driver.query(query, returns=(Node, Relationship, Node), data_contents=True)
            if results:
                edges = [x for x in results.rows]
        except CypherException as ce:
            log.error(ce)

        return edges

    def load_nodes(self, nodes: List) -> None:
        """
        Load nodes into an instance of BaseGraph

        Parameters
        ----------
        nodes: List
            A list of nodes

        """
        for node in nodes:
            if node['id'] not in self.seen_nodes:
                yield self.load_node(node)

    def load_node(self, node: Dict) -> Tuple:
        """
        Load node into an instance of BaseGraph

        Parameters
        ----------
        node: Dict
            A node

        """
        self.node_count += 1
        # TODO: remove the seen_nodes
        self.seen_nodes.add(node['id'])
        if 'provided_by' in self.graph_metadata and 'provided_by' not in node.keys():
            node['provided_by'] = self.graph_metadata['provided_by']
        return node['id'], node
        #self.graph.add_node(node['id'], **node)

    def load_edges(self, edges: List) -> None:
        """
        Load edges into an instance of BaseGraph

        Parameters
        ----------
        edges: List
            A list of edge records

        """
        for record in edges:
            print(record)
            self.edge_count += 1
            subject_node = record[0]
            edge = record[1]
            object_node = record[2]

            if 'subject' not in edge:
                edge['subject'] = subject_node['id']
            if 'object' not in edge:
                edge['object'] = object_node['id']

            s = self.load_node(subject_node)
            o = self.load_node(object_node)
            objs = []
            objs.append(s)
            objs.append(o)
            objs.append(self.load_edge([s[1], edge, o[1]]))
            for o in objs:
                yield o

    def load_edge(self, edge_record: List) -> Tuple:
        """
        Load an edge into an instance of BaseGraph

        Parameters
        ----------
        edge_record: List
            A 3-tuple edge record

        """

        subject_node = edge_record[0]
        edge = edge_record[1]
        object_node = edge_record[2]

        if 'provided_by' in self.graph_metadata and 'provided_by' not in edge.keys():
            edge['provided_by'] = self.graph_metadata['provided_by']
        if 'id' not in edge.keys():
            edge['id'] = generate_uuid()
        key = generate_edge_key(subject_node['id'], edge['predicate'], object_node['id'])
        print(subject_node['id'], object_node['id'], key, edge)
        return subject_node['id'], object_node['id'], key, edge
        #self.graph.add_edge(subject_node['id'], object_node['id'], key, **edge)

    def get_pages(self, query_function, start: int = 0, end: Optional[int] = None, page_size: int = 50000, **kwargs: Any) -> Iterator:
        """
        Get pages of size ``page_size`` from Neo4j.
        Returns an iterator of pages where number of pages is (``end`` - ``start``)/``page_size``

        Parameters
        ----------
        query_function: func
            The function to use to fetch records. Usually this is ``self.get_nodes`` or ``self.get_edges``
        start: int
            Start for pagination
        end: Optional[int]
            End for pagination
        page_size: int
            Size of each page (``10000``, by default)
        kwargs: Dict
            Any additional arguments that might be relevant for ``query_function``

        Returns
        -------
        Iterator
            An iterator for a list of records from Neo4j. The size of the list is ``page_size``

        """
        # TODO: use async
        # itertools.count(0) starts counting from zero, and would run indefinitely without a return statement.
        # it's distinguished from applying a while loop via providing an index which is formative with the for statement
        for i in itertools.count(0):
            # First halt condition: page pointer exceeds the number of values allowed to be returned in total
            skip = start + (page_size * i)
            limit = page_size if end is None or skip + page_size <= end else end - skip
            if limit <= 0:
                return
            # execute query_function to get records
            records = query_function(skip=skip, limit=limit, **kwargs)
            # Second halt condition: no more data available
            if records:
                """
                * Yield halts execution until next call
                * Thus, the function continues execution upon next call
                * Therefore, a new page is calculated before record is instantiated again
                """
                yield records
            else:
                return

    def get_node_filter(self, key: str, variable: Optional[str] = None, prefix: Optional[str] = None, op: Optional[str] = None) -> str:
        """
        Get the value for node filter as defined by ``key``.
        This is used as a convenience method for generating cypher queries.

        Parameters
        ----------
        key: str
            Name of the node filter
        variable: Optional[str]
            Variable binding for cypher query
        prefix: Optional[str]
            Prefix for the cypher
        op: Optional[str]
            The operator

        Returns
        -------
        str
            Value corresponding to the given node filter `key`, formatted for CQL

        """
        value = ''
        if key in self.node_filters and self.node_filters[key]:
            if isinstance(self.node_filters[key], (list, set, tuple)):
                if key in {'category'}:
                    formatted = [f"{variable}{prefix}`{x}`" for x in self.node_filters[key]]
                    value = f" {op} ".join(formatted)
                elif key in {'provided_by'}:
                    formatted = [f"'{x}' IN {variable}{prefix}{key}" for x in self.node_filters['provided_by']]
                    value = f" {op} ".join(formatted)
                else:
                    formatted = []
                    for v in self.node_filters[key]:
                        formatted.append(f"{variable}{prefix}{key} = '{v}'")
                    value = f" {op} ".join(formatted)
            elif isinstance(self.node_filters[key], str):
                value = f"{variable}{prefix}{key} = '{self.node_filters[key]}'"
            else:
                log.error(f"Unexpected {key} node filter of type {type(self.node_filters[key])}")
        return value

    def get_edge_filter(self, key: str, variable: Optional[str] = None, prefix: Optional[str] = None, op: Optional[str] = None) -> str:
        """
        Get the value for edge filter as defined by ``key``.
        This is used as a convenience method for generating cypher queries.

        Parameters
        ----------
        key: str
            Name of the edge filter
        variable: Optional[str]
            Variable binding for cypher query
        prefix: Optional[str]
            Prefix for the cypher
        op: Optional[str]
            The operator

        Returns
        -------
        str
            Value corresponding to the given edge filter `key`, formatted for CQL

        """
        value = ''
        if key in self.edge_filters and self.edge_filters[key]:
            if isinstance(self.edge_filters[key], (list, set, tuple)):
                if key in {'subject_category', 'object_category'}:
                    formatted = [f"{variable}{prefix}`{x}`" for x in self.edge_filters[key]]
                    value = f" {op} ".join(formatted)
                elif key == 'predicate':
                    formatted = [f"'{x}'" for x in self.edge_filters['predicate']]
                    value = f"type({variable}) IN [{', '.join(formatted)}]"
                elif key == 'provided_by':
                    formatted = [f"'{x}' IN {variable}{prefix}{key}" for x in self.edge_filters['provided_by']]
                    value = f" {op} ".join(formatted)
                else:
                    formatted = []
                    for v in self.edge_filters[key]:
                        formatted.append(f"{variable}{prefix}{key} = '{v}'")
                    value = f" {op} ".join(formatted)
            elif isinstance(self.edge_filters[key], str):
                value = f"{variable}{prefix}{key} = '{self.edge_filters[key]}'"
            else:
                log.error(f"Unexpected {key} edge filter of type {type(self.edge_filters[key])}")
        return value
