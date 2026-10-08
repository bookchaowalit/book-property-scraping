---
title: Book Property Scraping — Product Card
doc_id: CARD-book-property-scraping
doc_type: product-card
verdict: showcase
version: 0.1
date: 2026-10-08
status: ร่างเพื่อพิจารณา
owner: Product owner (Book Dev)
---

# Book Property Scraping — Product Card

## 1. สรุปคุณค่าในหนึ่งประโยค

ต้นแบบที่ช่วยเจ้าของติดตามประกาศคอนโดในกรุงเทพฯ และตรวจจับราคาที่ลดลงเทียบกับประวัติครั้งก่อน

## 2. ปัญหาและผู้ใช้เป้าหมาย

- การเฝ้าดูราคาคอนโดด้วยมือเสียเวลา และราคาที่ลดลงมักเห็นช้า
- ผู้ใช้หลักคือเจ้าของ repo เอง (เครื่องมือส่วนตัว) README ระบุ Tier C / tool prototype

## 3. สิ่งที่ทำได้จริงตอนนี้

- `scrape_property_listings.py` ดึงหนึ่งหน้าต่อประเภทประกาศ เขียน `property_listings.csv` และ `property_history.csv` แบบ atomic
- ตรวจราคาลดด้วย key จาก URL ที่ canonicalise แล้ว และ `--alert-drop-pct`
- `property/ddproperty_scraper.py` parse ข้อมูลจาก DDProperty (มี fixture `__NEXT_DATA__`)
- เมื่อหน้าตรงว่าง จะ fallback ไป scrape หน้าผลค้นหา Brave/Bing/Google หรือ Firecrawl ถ้ามี key
- test 9 ไฟล์ (parser, persistence, dry-run, flow)

## 4. หลักฐานสถานะ

- Stack: Python
- Commits: 15 (แรก 2026-07-09 → ล่าสุด 2026-10-01), branch `main`; working tree สะอาด
- Source: 11 ไฟล์ / 1,665 บรรทัด; test 9 ไฟล์
- CI: 1 workflow
- Deploy config: ไม่มี
- Live URL: ไม่พบใน repo

## 5. คุณค่าและจุดต่าง

- แสดงทักษะ scraping ที่ระวังข้อมูลเสีย (atomic write, URL canonicalisation, history)
- คู่แข่งคือฟีเจอร์แจ้งเตือนในพอร์ทัลอสังหาเอง ซึ่งใช้ง่ายกว่า
- มุมรายได้: บริการแจ้งราคาลดสำหรับนักลงทุนคอนโด **[สมมติฐาน]** ติดปัญหาเงื่อนไขการใช้เว็บต้นทาง

## 6. ช่องว่างสำคัญ

- README ยอมรับว่าไม่มี retry/backoff และไม่ตรวจ robots.txt และส่ง User-Agent แบบ browser
- fallback ไป scrape เครื่องมือค้นหาขัดเงื่อนไขของผู้ให้บริการ (README ระบุเอง) ต้องตัดออกก่อนใช้จริง
- ไม่มี scheduler หรือช่องทางแจ้งเตือนที่ทำงานจริง **[ต้องยืนยัน]**

## 7. คำตัดสิน

**showcase** — มีโค้ดและ test จริง เป็นหลักฐานความกว้างด้าน scraping แต่ติดปัญหาเงื่อนไขการใช้ข้อมูลและไม่มีผู้ใช้นอกจากเจ้าของ

จะเป็น `invest` ได้เมื่อมีแหล่งข้อมูลที่อนุญาต (API/feed) และเจ้าของใช้แจ้งเตือนจริงต่อเนื่อง; ถ้าไม่ได้ใช้เลยใน 3 เดือน ให้พิจารณา `archive`

## 8. ขั้นต่อไป

1. ตัด fallback ที่ scrape เครื่องมือค้นหาออก หรือปิดเป็นค่าเริ่มต้น
2. ทำ HTTP helper แบบ polite เหมือน `book-restaurant-scraping` (retry/backoff, User-Agent ระบุตัว)
3. ตัดสินใจว่าใช้เป็นเครื่องมือส่วนตัวจริงหรือเก็บเป็น portfolio

## การอนุมัติ

| บทบาท | สถานะ | วันที่ | ลงนาม |
|---|---|---|---|
| Product owner (Book Dev) | รอพิจารณา | — | ________ |

## แหล่งข้อมูล

- `README.md`
- `scrape_property_listings.py`
- `property/ddproperty_scraper.py`
- `tests/`
