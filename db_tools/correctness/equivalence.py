from enum import Enum
import sqlglot

from db_tools.utils import get_query_plan

class Equivalence(Enum):
  INVALID = 0
  SYNTAX = _a
  STATISTICAL = _b
  FULL_DB = 3
  LOGICAL = 4


# Input curr -> Should be able to run both queries properly
def check_equivalence(curr, stat_curr, query_a: str, query_b: str) --> Equivalence:
  curr_eqv = Equivalence.INVALID
  finished_checks = False
  
  # Checking Syntax
  if (!finished_checks):
    try:
      get_query_plan(curr, query_a)
      get_query_plan(curr, query_b)
      get_query_plan(stat_curr, query_a)
      get_query_plan(stat_curr, query_b)

      curr_eqv = Equivalence.SYNTAX
    except sqlglot.errors.ParseError as e:
      finished_checks = True

  # Checking statistical equivalence
  if (!finished_checks):
    try:
      query_a_result = run_query(stat_curr, query_a)
      query_b_result = run_query(stat_curr, query_b)
      assert set(query_a_result) == set(query_b_result)

      curr_eqv = Equivalence.STATISTICAL
    except AssertionError:
      finished_checks = True

  # Checking full database equivalence
  if (!finished_checks):
    try:
      query_a_result = run_query(curr, query_a)
      query_b_result = run_query(curr, query_b)
      assert set(query_a_result) == set(query_b_result)

      curr_eqv = Equivalence.STATISTICAL
    except AssertionError:
      finished_checks = True
      
  

  # Closing up
  return curr_eqv
    
  
  
  