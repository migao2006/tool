alter table market_data.backtest_runs drop constraint if exists backtest_runs_cost_multiplier_check;
alter table market_data.backtest_runs add constraint backtest_runs_cost_multiplier_check check (cost_multiplier in (0.75, 1.0, 1.5, 2.0));
