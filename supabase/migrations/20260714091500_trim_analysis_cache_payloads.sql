-- Price history has its own normalized table. Keeping a second 180-row copy in
-- ranking JSON makes public responses unnecessarily large.
update public.stock_analysis_cache
set analysis = analysis - 'priceHistory',
    updated_at = now()
where analysis ? 'priceHistory';
