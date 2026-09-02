-- Template for the company's read-only integration surface.
-- The real company runs their own version; VIEWs hide sensitive columns.

DROP VIEW IF EXISTS v_stok;
DROP TABLE IF EXISTS stok_barang;

CREATE TABLE stok_barang (
    id          serial PRIMARY KEY,
    nama        text NOT NULL,
    sku         text NOT NULL,
    qty         integer NOT NULL,
    satuan      text NOT NULL DEFAULT 'pcs',
    gudang      text NOT NULL,
    harga_beli  numeric(12,2)          -- sensitive: excluded from the view
);

CREATE VIEW v_stok AS
    SELECT nama, sku, qty, satuan, gudang FROM stok_barang;

INSERT INTO stok_barang (nama, sku, qty, satuan, gudang, harga_beli) VALUES
 ('Kabel USB Type-C 1m',       'KBL-USBC-1M',  40, 'pcs', 'Gudang A', 12000),
 ('Kabel USB Type-C 2m',       'KBL-USBC-2M',  15, 'pcs', 'Gudang A', 18000),
 ('Kabel HDMI 1.5m',           'KBL-HDMI-15',  22, 'pcs', 'Gudang B', 25000),
 ('Adaptor Charger 20W',       'ADP-20W',       8, 'pcs', 'Gudang A', 45000),
 ('Adaptor Charger 65W',       'ADP-65W',       5, 'pcs', 'Gudang B', 120000),
 ('Mouse Wireless',            'MSE-WL-01',    30, 'pcs', 'Gudang A', 55000),
 ('Keyboard Mekanik',          'KBD-MEC-01',   12, 'pcs', 'Gudang B', 350000),
 ('Flashdisk 64GB',            'FD-64',        70, 'pcs', 'Gudang A', 40000),
 ('Flashdisk 128GB',           'FD-128',       25, 'pcs', 'Gudang A', 75000),
 ('Hardisk Eksternal 1TB',     'HDD-EXT-1T',    9, 'pcs', 'Gudang B', 650000),
 ('Powerbank 10000mAh',        'PB-10K',       18, 'pcs', 'Gudang A', 150000),
 ('Powerbank 20000mAh',        'PB-20K',       11, 'pcs', 'Gudang B', 250000),
 ('Headset Bluetooth',         'HST-BT-01',    14, 'pcs', 'Gudang A', 180000),
 ('Webcam HD 1080p',           'WBC-1080',      7, 'pcs', 'Gudang B', 220000),
 ('Kabel LAN Cat6 5m',         'KBL-LAN-5M',   33, 'pcs', 'Gudang A', 30000);
