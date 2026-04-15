# Bug Fix: Website Body Filter Not Returning WRC Decisions

## The Problem

When scraping the WRC website, we were only getting **23 documents** instead of the expected **~235 documents** for the date range Oct 1 - Nov 1, 2025.

### Investigation

We checked the database and found:
```
Documents by body (2025-10 to 2025-11):
  Labour Court: 23

Total documents: 23
```

Only Labour Court documents were being scraped. WRC decisions (ADJ-* identifiers) were missing.

### Root Cause

**The website's body filter is broken for WRC (body=4) decisions.**

Testing on the website directly:

| URL | Results |
|-----|---------|
| `?decisions=1&body=3&from=1/10/2025&to=1/11/2025` (Labour Court) | ✅ 23 results |
| `?decisions=1&body=4&from=1/10/2025&to=1/11/2025` (WRC) | ❌ 0 results |
| `?decisions=1&from=1/10/2025&to=1/11/2025` (NO body filter) | ✅ 235 results |

When searching **without** a body filter, the website returns ALL decisions including WRC's ADJ-* documents. But filtering by `body=4` returns nothing.

---

## The Solution

### Approach
1. **Remove the body filter entirely** - search without specifying a body
2. **Detect body from identifier prefix** - infer which body each document belongs to based on its reference number

### Why This Works
- Each body uses distinct identifier prefixes (ADJ-*, LCR*, DEC-*, etc.)
- Searching without body filter returns everything
- We can accurately categorize documents after scraping

---

## Code Changes

### Change 1: `start_requests()` - Removed body loop

**BEFORE:**
```python
def start_requests(self) -> Iterator[scrapy.Request]:
    # Determine which bodies to scrape
    bodies_to_scrape = (
        [self.body_filter] if self.body_filter 
        else list(self.BODIES.keys())
    )
    
    # Generate partitions
    for partition_start, partition_end in self._generate_partitions():
        partition_date = partition_start.strftime("%Y-%m")
        
        for body_id in bodies_to_scrape:  # ← Loop through 4 bodies
            body_name = self.BODIES[body_id]
            
            url = self._build_search_url(
                from_date=partition_start,
                to_date=partition_end,
                body_id=body_id,  # ← Pass body to URL
                page=1
            )
            
            yield scrapy.Request(
                url=url,
                callback=self.parse_search_results,
                meta={
                    'partition_date': partition_date,
                    'body_id': body_id,      # ← Body in meta
                    'body_name': body_name,  # ← Body in meta
                    'page': 1,
                }
            )
```

**AFTER:**
```python
def start_requests(self) -> Iterator[scrapy.Request]:
    # Generate partitions
    for partition_start, partition_end in self._generate_partitions():
        partition_date = partition_start.strftime("%Y-%m")
        
        # Build search URL (no body filter - gets all bodies)
        url = self._build_search_url(
            from_date=partition_start,
            to_date=partition_end,
            page=1
        )
        
        yield scrapy.Request(
            url=url,
            callback=self.parse_search_results,
            meta={
                'partition_date': partition_date,
                'page': 1,
                # No body_id or body_name - detect from identifier later
            },
        )
```

**Key differences:**
- Removed the `for body_id in bodies_to_scrape:` loop
- One request per partition (not 4)
- No `body_id`/`body_name` in meta data

---

### Change 2: `_build_search_url()` - Removed body parameter

**BEFORE:**
```python
def _build_search_url(self, from_date: datetime, to_date: datetime,
                      body_id: int, page: int = 1) -> str:
    from_str = f"{from_date.day}/{from_date.month}/{from_date.year}"
    to_str = f"{to_date.day}/{to_date.month}/{to_date.year}"
    
    params = {
        'decisions': '1',
        'body': str(body_id),  # ← Body filter included
        'from': from_str,
        'to': to_str,
        'pageNumber': str(page),
    }
    
    return f"{self.BASE_SEARCH_URL}?{urlencode(params)}"
```

**AFTER:**
```python
def _build_search_url(self, from_date: datetime, to_date: datetime,
                      page: int = 1) -> str:
    from_str = f"{from_date.day}/{from_date.month}/{from_date.year}"
    to_str = f"{to_date.day}/{to_date.month}/{to_date.year}"
    
    params = {
        'decisions': '1',
        # No body filter - website filter is broken for WRC decisions
        'from': from_str,
        'to': to_str,
        'pageNumber': str(page),
    }
    
    return f"{self.BASE_SEARCH_URL}?{urlencode(params)}"
```

**Key differences:**
- Removed `body_id` parameter
- Removed `'body': str(body_id)` from params
- Added comment explaining why

---

### Change 3: Added `_detect_body_from_identifier()` - New method

**NEW METHOD:**
```python
def _detect_body_from_identifier(self, identifier: str) -> str:
    """
    Detect the body (tribunal/commission) from the identifier prefix.
    
    Identifier patterns:
    - ADJ-*, IR-SC-* = Workplace Relations Commission
    - LCR*, UDD*, DWT*, EDA*, PWD* = Labour Court
    - DEC-* = Equality Tribunal  
    - UD*, MN*, RP*, TE* = Employment Appeals Tribunal
    """
    identifier_upper = identifier.upper()
    
    # WRC identifiers
    if identifier_upper.startswith('ADJ-') or identifier_upper.startswith('IR'):
        return "Workplace Relations Commission"
    
    # Labour Court identifiers
    if any(identifier_upper.startswith(prefix) for prefix in ['LCR', 'UDD', 'DWT', 'EDA', 'PWD']):
        return "Labour Court"
    
    # Equality Tribunal identifiers
    if identifier_upper.startswith('DEC-'):
        return "Equality Tribunal"
    
    # Employment Appeals Tribunal identifiers
    if any(identifier_upper.startswith(prefix) for prefix in ['UD', 'MN', 'RP', 'TE']):
        return "Employment Appeals Tribunal"
    
    # Default to WRC if unknown
    return "Workplace Relations Commission"
```

**Identifier prefix meanings:**

| Prefix | Full Meaning | Body |
|--------|--------------|------|
| ADJ | Adjudication | Workplace Relations Commission |
| IR-SC | Industrial Relations - Special Case | Workplace Relations Commission |
| LCR | Labour Court Recommendation | Labour Court |
| UDD | Unfair Dismissal Determination | Labour Court |
| DWT | Determination of Working Time | Labour Court |
| EDA | Equality Determination Appeal | Labour Court |
| PWD | Payment of Wages Determination | Labour Court |
| DEC | Decision | Equality Tribunal |
| UD | Unfair Dismissals | Employment Appeals Tribunal |
| MN | Minimum Notice | Employment Appeals Tribunal |
| RP | Redundancy Payments | Employment Appeals Tribunal |
| TE | Terms of Employment | Employment Appeals Tribunal |

---

### Change 4: `parse_search_results()` - Detect body per item

**BEFORE:**
```python
def parse_search_results(self, response: Response) -> Iterator[Any]:
    partition_date = response.meta['partition_date']
    body_id = response.meta['body_id']      # ← Get from meta
    body_name = response.meta['body_name']  # ← Get from meta
    current_page = response.meta['page']
    
    # ... extraction code ...
    
    item['body'] = body_name  # ← Use meta value (WRONG - always same body)
```

**AFTER:**
```python
def parse_search_results(self, response: Response) -> Iterator[Any]:
    partition_date = response.meta['partition_date']
    current_page = response.meta['page']
    # No body_id or body_name from meta
    
    # ... extraction code ...
    
    # Detect body from identifier prefix
    body_name = self._detect_body_from_identifier(identifier)  # ← Detect per item!
    
    item['body'] = body_name  # ← Correct body for each document
```

**Key difference:**
- Body is detected **per document** based on its identifier
- Not assumed from the search URL

---

## Results

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| Documents scraped | 23 | 235 |
| Bodies covered | Labour Court only | All 4 bodies |
| Requests per partition | 4 (one per body) | 1 (all bodies) |

---

## Interview Explanation

> "The website's body filter was broken for WRC decisions - searching with `body=4` returned zero results. I discovered this by testing the URLs directly. The fix was to remove the body filter from search URLs entirely, which returns all decisions. Since we still need to know which body each document belongs to, I added logic to detect the body from the identifier prefix - each tribunal uses distinct prefixes like ADJ for WRC, LCR for Labour Court, etc."

---

## Key Lessons

1. **Don't trust website filters** - always verify they return expected results
2. **Test with actual data** - comparing expected vs actual counts revealed the bug
3. **Document domain knowledge** - the identifier prefix meanings are valuable context
4. **Graceful degradation** - when a feature is broken, find a workaround that still categorizes data correctly
