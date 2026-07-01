import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select
from database import get_session, init_db, engine
from models import Symbol, User, Plan, MarketSettings, SystemSettings

SAUDI_SYMBOLS = [
    # البنوك
    ("1120.SR", "1120.SR", "الراجحي", "Al Rajhi Bank", "البنوك", "SAUDI"),
    ("1180.SR", "1180.SR", "البنك الأهلي", "National Commercial Bank", "البنوك", "SAUDI"),
    ("1010.SR", "1010.SR", "بنك الرياض", "Riyad Bank", "البنوك", "SAUDI"),
    ("1140.SR", "1140.SR", "بنك البلاد", "Bank AlBilad", "البنوك", "SAUDI"),
    ("1020.SR", "1020.SR", "بنك الجزيرة", "Bank AlJazira", "البنوك", "SAUDI"),
    ("1040.SR", "1040.SR", "البنك العربي", "Arab National Bank", "البنوك", "SAUDI"),
    ("1060.SR", "1060.SR", "بنك الخليج", "Gulf Bank", "البنوك", "SAUDI"),
    ("1030.SR", "1030.SR", "بنك الاستثمار", "Saudi Investment Bank", "البنوك", "SAUDI"),
    ("1080.SR", "1080.SR", "البنك السعودي الفرنسي", "Banque Saudi Fransi", "البنوك", "SAUDI"),
    ("1050.SR", "1050.SR", "بنك السعودي الهولندي", "Saudi Dutch Bank", "البنوك", "SAUDI"),
    # الطاقة
    ("2222.SR", "2222.SR", "أرامكو السعودية", "Saudi Aramco", "الطاقة", "SAUDI"),
    ("2380.SR", "2380.SR", "بترو رابغ", "Petro Rabigh", "الطاقة", "SAUDI"),
    ("4200.SR", "4200.SR", "لدائن", "ALD", "الطاقة", "SAUDI"),
    # المواد الأساسية
    ("2010.SR", "2010.SR", "سابك", "SABIC", "المواد الأساسية", "SAUDI"),
    ("1211.SR", "1211.SR", "معادن", "Maaden", "المواد الأساسية", "SAUDI"),
    ("1150.SR", "1150.SR", "كيمانول", "Kayan", "المواد الأساسية", "SAUDI"),
    ("2060.SR", "2060.SR", "التصنيع", "Tasnee", "المواد الأساسية", "SAUDI"),
    ("2250.SR", "2250.SR", "سبكيم", "Sipchem", "المواد الأساسية", "SAUDI"),
    ("2290.SR", "2290.SR", "ينساب", "Yansab", "المواد الأساسية", "SAUDI"),
    ("2170.SR", "2170.SR", "اللجين", "Alujain", "المواد الأساسية", "SAUDI"),
    ("2160.SR", "2160.SR", "نسيج", "Naseej", "المواد الأساسية", "SAUDI"),
    ("2240.SR", "2240.SR", "سابوك", "Sabic Agri-Nutrients", "المواد الأساسية", "SAUDI"),
    ("2150.SR", "2150.SR", "الزجاج", "Saudi Glass", "المواد الأساسية", "SAUDI"),
    ("2310.SR", "2310.SR", "سابك للمغذيات", "SABIC Agri-Nutrients", "المواد الأساسية", "SAUDI"),
    ("2330.SR", "2330.SR", "أسمك", "ASMK", "المواد الأساسية", "SAUDI"),
    ("2350.SR", "2350.SR", "المتحدة للتأمين", "United Insurance", "المواد الأساسية", "SAUDI"),
    ("2360.SR", "2360.SR", "الكهرباء", "SEC", "المواد الأساسية", "SAUDI"),
    # الاتصالات
    ("7010.SR", "7010.SR", "stc", "Saudi Telecom", "الاتصالات", "SAUDI"),
    ("7030.SR", "7030.SR", "زين", "Zain KSA", "الاتصالات", "SAUDI"),
    ("7020.SR", "7020.SR", "اتحاد اتصالات", "Etihad Etisalat (Mobily)", "الاتصالات", "SAUDI"),
    ("7040.SR", "7040.SR", "الاتصالات السعودية", "Saudi Telecom", "الاتصالات", "SAUDI"),
    # التأمين
    ("8010.SR", "8010.SR", "تكافل الراجحي", "Takaful Al Rajhi", "التأمين", "SAUDI"),
    ("8020.SR", "8020.SR", "التعاونية", "Allianz Saudi Fransi", "التأمين", "SAUDI"),
    ("8030.SR", "8030.SR", "درع العرب", "Arab Shield", "التأمين", "SAUDI"),
    ("8040.SR", "8040.SR", "السعودية الهندية", "Saudi Indian", "التأمين", "SAUDI"),
    ("8050.SR", "8050.SR", "ملاذ للتأمين", "Malath Insurance", "التأمين", "SAUDI"),
    ("8060.SR", "8060.SR", "أسيج", "ACIG", "التأمين", "SAUDI"),
    ("8070.SR", "8070.SR", "الدرعية للتأمين", "Al Dhara Insurance", "التأمين", "SAUDI"),
    ("8080.SR", "8080.SR", "أبشر", "Absher", "التأمين", "SAUDI"),
    ("8090.SR", "8090.SR", "سايكو", "SAICO", "التأمين", "SAUDI"),
    ("8100.SR", "8100.SR", "ولاء", "Walaa", "التأمين", "SAUDI"),
    ("8110.SR", "8110.SR", "العربية للتأمين", "Arabian Insurance", "التأمين", "SAUDI"),
    ("8120.SR", "8120.SR", "الخليجية للتأمين", "Gulf Insurance", "التأمين", "SAUDI"),
    ("8130.SR", "8130.SR", "أمانة للتأمين", "Amana Insurance", "التأمين", "SAUDI"),
    ("8140.SR", "8140.SR", "الراجحي للتأمين", "Al Rajhi Insurance", "التأمين", "SAUDI"),
    ("8150.SR", "8150.SR", "الوطنية للتأمين", "National Insurance", "التأمين", "SAUDI"),
    ("8160.SR", "8160.SR", "ميدغلف", "MedGulf", "التأمين", "SAUDI"),
    ("8170.SR", "8170.SR", "بوله", "Bupa Arabia", "التأمين", "SAUDI"),
    ("8180.SR", "8180.SR", "الأهلية للتأمين", "Al Ahli Insurance", "التأمين", "SAUDI"),
    ("8190.SR", "8190.SR", "شبكة", "Shabakah", "التأمين", "SAUDI"),
    # الرعاية الصحية
    ("4002.SR", "4002.SR", "مجموعة مستشفيات السعودي الألماني", "Saudi German Hospital", "الرعاية الصحية", "SAUDI"),
    ("4003.SR", "4003.SR", "الحمادي", "Al Hammadi", "الرعاية الصحية", "SAUDI"),
    ("4004.SR", "4004.SR", "دله", "Dallah Healthcare", "الرعاية الصحية", "SAUDI"),
    ("4005.SR", "4005.SR", "المواساة", "Mouwasat", "الرعاية الصحية", "SAUDI"),
    ("4006.SR", "4006.SR", "المستشفي التخصصي", "Specialized Hospital", "الرعاية الصحية", "SAUDI"),
    ("4007.SR", "4007.SR", "أرما", "Arma", "الرعاية الصحية", "SAUDI"),
    ("4008.SR", "4008.SR", "مهارة", "Maharah", "الرعاية الصحية", "SAUDI"),
    ("4009.SR", "4009.SR", "العناية", "Al Enaya", "الرعاية الصحية", "SAUDI"),
    ("4010.SR", "4010.SR", "أكسا", "Axa", "الرعاية الصحية", "SAUDI"),
    ("4011.SR", "4011.SR", "الحياة", "Al Hayat", "الرعاية الصحية", "SAUDI"),
    # العقار
    ("4220.SR", "4220.SR", "إعمار المدينة", "Emaar Med", "العقار", "SAUDI"),
    ("4230.SR", "4230.SR", "معمور", "Mamour", "العقار", "SAUDI"),
    ("4240.SR", "4240.SR", "المراكز", "Centers", "العقار", "SAUDI"),
    ("4250.SR", "4250.SR", "جبل عمر", "Jabal Omar", "العقار", "SAUDI"),
    ("4260.SR", "4260.SR", "طيبة", "Taiba", "العقار", "SAUDI"),
    ("4270.SR", "4270.SR", "المدينة", "Al Madina", "العقار", "SAUDI"),
    ("4280.SR", "4280.SR", "الراجحي ريت", "Al Rajhi REIT", "العقار", "SAUDI"),
    ("4290.SR", "4290.SR", "سبكيم ريت", "Sipchem REIT", "العقار", "SAUDI"),
    ("4300.SR", "4300.SR", "الرياض ريت", "Riyad REIT", "العقار", "SAUDI"),
    ("4310.SR", "4310.SR", "بنان", "Banan", "العقار", "SAUDI"),
    # الأغذية والزراعة
    ("2050.SR", "2050.SR", "المراعي", "Almarai", "الأغذية", "SAUDI"),
    ("2100.SR", "2100.SR", "الوطنية للزراعة", "National Agriculture", "الأغذية", "SAUDI"),
    ("2200.SR", "2200.SR", "جرير", "Jarir", "الأغذية", "SAUDI"),
    ("2280.SR", "2280.SR", "أنعام", "Anam", "الأغذية", "SAUDI"),
    ("2300.SR", "2300.SR", "الحماد", "Al Hammad", "الأغذية", "SAUDI"),
    ("2320.SR", "2320.SR", "الشرقية", "Al Sharqia", "الأغذية", "SAUDI"),
    ("2340.SR", "2340.SR", "أسواق العثيم", "Othaim Markets", "الأغذية", "SAUDI"),
    ("2350.SR", "2350.SR", "أسواق المزرعة", "Almazraa", "الأغذية", "SAUDI"),
    # الخدمات الاستهلاكية
    ("4001.SR", "4001.SR", "الخريف", "Al Khorayef", "الخدمات", "SAUDI"),
    ("4080.SR", "4080.SR", "الخليج للتدريب", "Gulf Training", "الخدمات", "SAUDI"),
    ("4090.SR", "4090.SR", "الباحة", "Al Baha", "الخدمات", "SAUDI"),
    ("4100.SR", "4100.SR", "الطيار", "Al Tayyar", "الخدمات", "SAUDI"),
    ("4110.SR", "4110.SR", "ماس", "MAS", "الخدمات", "SAUDI"),
    ("4120.SR", "4120.SR", "الدريس", "Aldrees", "الخدمات", "SAUDI"),
    ("4130.SR", "4130.SR", "مجموعة فتيحي", "Fityahi Group", "الخدمات", "SAUDI"),
    ("4140.SR", "4140.SR", "العبداللطيف", "Al Abdulatif", "الخدمات", "SAUDI"),
    ("4150.SR", "4150.SR", "الجزيرة للخدمات", "Al Jazira Services", "الخدمات", "SAUDI"),
    ("4160.SR", "4160.SR", "باعظيم", "Baazim", "الخدمات", "SAUDI"),
    # التجزئة
    ("4170.SR", "4170.SR", "مكتبة جرير", "Jarir Bookstore", "التجزئة", "SAUDI"),
    ("4180.SR", "4180.SR", "الحكير", "Al Hokair", "التجزئة", "SAUDI"),
    ("4190.SR", "4190.SR", "شمس", "Shams", "التجزئة", "SAUDI"),
    ("4191.SR", "4191.SR", "المتجر", "Al Matjar", "التجزئة", "SAUDI"),
    ("4192.SR", "4192.SR", "السريع", "Al Saree", "التجزئة", "SAUDI"),
    ("4193.SR", "4193.SR", "الجماعي", "Al Jammaz", "التجزئة", "SAUDI"),
    ("4194.SR", "4194.SR", "السنارة", "Al Sanara", "التجزئة", "SAUDI"),
    ("4195.SR", "4195.SR", "قوي", "Qawi", "التجزئة", "SAUDI"),
    # المرافق العامة
    ("4196.SR", "4196.SR", "المياه الوطنية", "National Water", "المرافق", "SAUDI"),
    ("4197.SR", "4197.SR", "كهرباء السعودية", "Saudi Electricity", "المرافق", "SAUDI"),
    ("4198.SR", "4198.SR", "الغاز", "Gas", "المرافق", "SAUDI"),
    # الاستثمار والتمويل
    ("4199.SR", "4199.SR", "مجموعة السعودية", "Saudi Group", "الاستثمار", "SAUDI"),
    ("4200.SR", "4200.SR", "الاستثمار", "Investment", "الاستثمار", "SAUDI"),
    ("4210.SR", "4210.SR", "عبدالله هاشم", "Abdullah Hashim", "الاستثمار", "SAUDI"),
]

US_SYMBOLS = [
    # التقنية
    ("AAPL", "AAPL", "أبل", "Apple Inc.", "التقنية", "US"),
    ("MSFT", "MSFT", "مايكروسوفت", "Microsoft Corp.", "التقنية", "US"),
    ("NVDA", "NVDA", "نفيديا", "NVIDIA Corp.", "التقنية", "US"),
    ("AMZN", "AMZN", "أمازون", "Amazon.com Inc.", "التقنية", "US"),
    ("GOOGL", "GOOGL", "غوغل", "Alphabet Inc.", "التقنية", "US"),
    ("META", "META", "ميتا", "Meta Platforms Inc.", "التقنية", "US"),
    ("AMD", "AMD", "أي إم دي", "Advanced Micro Devices", "التقنية", "US"),
    ("INTC", "INTC", "إنتل", "Intel Corp.", "التقنية", "US"),
    ("CRM", "CRM", "سيلزفورس", "Salesforce Inc.", "التقنية", "US"),
    ("ADBE", "ADBE", "أدوبي", "Adobe Inc.", "التقنية", "US"),
    ("ORCL", "ORCL", "أوراكل", "Oracle Corp.", "التقنية", "US"),
    ("CSCO", "CSCO", "سيسكو", "Cisco Systems", "التقنية", "US"),
    ("IBM", "IBM", "آي بي إم", "IBM Corp.", "التقنية", "US"),
    ("QCOM", "QCOM", "كوالكوم", "Qualcomm Inc.", "التقنية", "US"),
    ("TXN", "TXN", "تكساس إنسترومنتس", "Texas Instruments", "التقنية", "US"),
    ("AVGO", "AVGO", "برودكوم", "Broadcom Inc.", "التقنية", "US"),
    ("MU", "MU", "مايكرون", "Micron Technology", "التقنية", "US"),
    # الذكاء الاصطناعي
    ("AI", "AI", "C3.ai", "C3.ai Inc.", "الذكاء الاصطناعي", "US"),
    ("PLTR", "PLTR", "بالانتير", "Palantir Technologies", "الذكاء الاصطناعي", "US"),
    ("SOUN", "SOUN", "سونداون", "SoundHound AI", "الذكاء الاصطناعي", "US"),
    ("UPST", "UPST", "أبستارت", "Upstart Holdings", "الذكاء الاصطناعي", "US"),
    # السيارات الكهربائية
    ("TSLA", "TSLA", "تسلا", "Tesla Inc.", "السيارات الكهربائية", "US"),
    ("RIVN", "RIVN", "ريفيان", "Rivian Automotive", "السيارات الكهربائية", "US"),
    ("LCID", "LCID", "لوسيد", "Lucid Group", "السيارات الكهربائية", "US"),
    ("F", "F", "فورد", "Ford Motor Co.", "السيارات الكهربائية", "US"),
    ("GM", "GM", "جنرال موتورز", "General Motors", "السيارات الكهربائية", "US"),
    # البنوك
    ("JPM", "JPM", "جي بي مورغان", "JPMorgan Chase", "البنوك", "US"),
    ("BAC", "BAC", "بنك أوف أمريكا", "Bank of America", "البنوك", "US"),
    ("WFC", "WFC", "ويلز فارجو", "Wells Fargo", "البنوك", "US"),
    ("C", "C", "سيتي غروب", "Citigroup Inc.", "البنوك", "US"),
    ("GS", "GS", "غولدمان ساكس", "Goldman Sachs", "البنوك", "US"),
    ("MS", "MS", "مورغان ستانلي", "Morgan Stanley", "البنوك", "US"),
    # الطاقة
    ("XOM", "XOM", "إكسون موبيل", "Exxon Mobil Corp.", "الطاقة", "US"),
    ("CVX", "CVX", "شيفرون", "Chevron Corp.", "الطاقة", "US"),
    ("COP", "COP", "كونوكو فيليبس", "ConocoPhillips", "الطاقة", "US"),
    ("SLB", "SLB", "شلمبرجير", "Schlumberger", "الطاقة", "US"),
    ("OXY", "OXY", "أكسيدنتال", "Occidental Petroleum", "الطاقة", "US"),
    # الرعاية الصحية
    ("UNH", "UNH", "يونايتد هيلث", "UnitedHealth Group", "الرعاية الصحية", "US"),
    ("JNJ", "JNJ", "جونسون آند جونسون", "Johnson & Johnson", "الرعاية الصحية", "US"),
    ("PFE", "PFE", "فايزر", "Pfizer Inc.", "الرعاية الصحية", "US"),
    ("ABBV", "ABBV", "أبيفي", "AbbVie Inc.", "الرعاية الصحية", "US"),
    ("MRK", "MRK", "ميرك", "Merck & Co.", "الرعاية الصحية", "US"),
    ("LLY", "LLY", "إيلي ليلي", "Eli Lilly & Co.", "الرعاية الصحية", "US"),
    # المستهلك
    ("WMT", "WMT", "وول مارت", "Walmart Inc.", "التجزئة", "US"),
    ("COST", "COST", "كوستكو", "Costco Wholesale", "التجزئة", "US"),
    ("HD", "HD", "هوم ديبوت", "Home Depot Inc.", "التجزئة", "US"),
    ("MCD", "MCD", "ماكدونالدز", "McDonald's Corp.", "المستهلك", "US"),
    ("KO", "KO", "كوكاكولا", "Coca-Cola Co.", "المستهلك", "US"),
    ("PEP", "PEP", "بيبسيكو", "PepsiCo Inc.", "المستهلك", "US"),
    ("PG", "PG", "بروكتر أند غامبل", "Procter & Gamble", "المستهلك", "US"),
    ("NKE", "NKE", "نايك", "Nike Inc.", "المستهلك", "US"),
    ("SBUX", "SBUX", "ستاربكس", "Starbucks Corp.", "المستهلك", "US"),
    ("DIS", "DIS", "ديزني", "Walt Disney Co.", "المستهلك", "US"),
    ("NFLX", "NFLX", "نتفليكس", "Netflix Inc.", "المستهلك", "US"),
    # النقل والصناعة
    ("BA", "BA", "بوينغ", "Boeing Co.", "الصناعة", "US"),
    ("CAT", "CAT", "كاتربيلر", "Caterpillar Inc.", "الصناعة", "US"),
    ("GE", "GE", "جنرال إلكتريك", "General Electric", "الصناعة", "US"),
    ("UPS", "UPS", "يو بي إس", "United Parcel Service", "النقل", "US"),
    ("FDX", "FDX", "فيديكس", "FedEx Corp.", "النقل", "US"),
    ("DAL", "DAL", "دلتا", "Delta Air Lines", "النقل", "US"),
    ("UAL", "UAL", "يونايتد", "United Airlines", "النقل", "US"),
    ("AAL", "AAL", "أمريكان", "American Airlines", "النقل", "US"),
]

CRYPTO_SYMBOLS = [
    ("BTCUSDT", "BTC-USD", "بيتكوين", "Bitcoin", "العملات الرئيسية", "CRYPTO"),
    ("ETHUSDT", "ETH-USD", "إيثريوم", "Ethereum", "العملات الرئيسية", "CRYPTO"),
    ("BNBUSDT", "BNB-USD", "بي إن بي", "BNB", "العملات الرئيسية", "CRYPTO"),
    ("SOLUSDT", "SOL-USD", "سولانا", "Solana", "Layer 1", "CRYPTO"),
    ("XRPUSDT", "XRP-USD", "إكس آر بي", "XRP", "العملات الرئيسية", "CRYPTO"),
    ("ADAUSDT", "ADA-USD", "كاردانو", "Cardano", "Layer 1", "CRYPTO"),
    ("DOGEUSDT", "DOGE-USD", "دوجكوين", "Dogecoin", "Meme Coins", "CRYPTO"),
    ("MATICUSDT", "MATIC-USD", "بوليجون", "Polygon", "Layer 2", "CRYPTO"),
    ("DOTUSDT", "DOT-USD", "بولكادوت", "Polkadot", "Layer 1", "CRYPTO"),
    ("LINKUSDT", "LINK-USD", "تشين لينك", "Chainlink", "DeFi", "CRYPTO"),
    ("AVAXUSDT", "AVAX-USD", "أفالانش", "Avalanche", "Layer 1", "CRYPTO"),
    ("UNIUSDT", "UNI-USD", "يوني سواب", "Uniswap", "DeFi", "CRYPTO"),
    ("ATOMUSDT", "ATOM-USD", "كوزموس", "Cosmos", "Layer 1", "CRYPTO"),
    ("LTCUSDT", "LTC-USD", "لايتكوين", "Litecoin", "العملات الرئيسية", "CRYPTO"),
    ("BCHUSDT", "BCH-USD", "بيتكوين كاش", "Bitcoin Cash", "العملات الرئيسية", "CRYPTO"),
    ("TRXUSDT", "TRX-USD", "ترون", "TRON", "Layer 1", "CRYPTO"),
    ("APTUSDT", "APT-USD", "أبتوس", "Aptos", "Layer 1", "CRYPTO"),
    ("ARBUSDT", "ARB-USD", "أربيتروم", "Arbitrum", "Layer 2", "CRYPTO"),
    ("OPUSDT", "OP-USD", "أوبتيميزم", "Optimism", "Layer 2", "CRYPTO"),
    ("SUIUSDT", "SUI-USD", "سوي", "Sui", "Layer 1", "CRYPTO"),
    ("NEARUSDT", "NEAR-USD", "نير", "NEAR Protocol", "Layer 1", "CRYPTO"),
    ("FILUSDT", "FIL-USD", "فيل كوين", "Filecoin", "DeFi", "CRYPTO"),
    ("AAVEUSDT", "AAVE-USD", "آفي", "Aave", "DeFi", "CRYPTO"),
    ("CRVUSDT", "CRV-USD", "كارف", "Curve DAO", "DeFi", "CRYPTO"),
    ("SHIBUSDT", "SHIB-USD", "شيباتو", "Shiba Inu", "Meme Coins", "CRYPTO"),
    ("PEPEUSDT", "PEPE-USD", "بيبي", "Pepe", "Meme Coins", "CRYPTO"),
    ("FLOKIUSDT", "FLOKI-USD", "فلوكي", "Floki", "Meme Coins", "CRYPTO"),
    ("INJUSDT", "INJ-USD", "إينجيكتيف", "Injective", "DeFi", "CRYPTO"),
    ("MKRUSDT", "MKR-USD", "ميكر", "Maker", "DeFi", "CRYPTO"),
    ("RUNUSDT", "RUN-USD", "ثور تشين", "THORChain", "DeFi", "CRYPTO"),
    ("ETCUSDT", "ETC-USD", "إيثريوم كلاسيك", "Ethereum Classic", "Layer 1", "CRYPTO"),
    ("XLMUSDT", "XLM-USD", "ستيلار", "Stellar", "Layer 1", "CRYPTO"),
    ("ALGOUSDT", "ALGO-USD", "ألغوراند", "Algorand", "Layer 1", "CRYPTO"),
    ("FTMUSDT", "FTM-USD", "فانتوم", "Fantom", "Layer 1", "CRYPTO"),
    ("SANDUSDT", "SAND-USD", "ساند", "The Sandbox", "Meme Coins", "CRYPTO"),
    ("MANAUSDT", "MANA-USD", "مانا", "Decentraland", "Meme Coins", "CRYPTO"),
    ("AXSUSDT", "AXS-USD", "أكساي", "Axie Infinity", "Meme Coins", "CRYPTO"),
    ("GRTUSDT", "GRT-USD", "ذا غراف", "The Graph", "DeFi", "CRYPTO"),
    ("EGLDUSDT", "EGLD-USD", "إيجلد", "MultiversX", "Layer 1", "CRYPTO"),
    ("KSMUSDT", "KSM-USD", "كوساما", "Kusama", "Layer 1", "CRYPTO"),
]

SAUDI_SECTORS = [
    "البنوك", "الطاقة", "المواد الأساسية", "الاتصالات", "التأمين",
    "الرعاية الصحية", "العقار", "الأغذية", "الخدمات", "التجزئة",
    "المرافق", "الاستثمار",
]

US_CATEGORIES = [
    "التقنية", "الذكاء الاصطناعي", "السيارات الكهربائية", "البنوك",
    "الطاقة", "الرعاية الصحية", "التجزئة", "المستهلك", "الصناعة", "النقل",
]

CRYPTO_CATEGORIES = [
    "العملات الرئيسية", "Layer 1", "Layer 2", "DeFi", "Meme Coins",
]


async def seed_symbols():
    async with get_session() as session:
        existing = await session.execute(select(Symbol).limit(1))
        if existing.scalar_one_or_none():
            print("Symbols already seeded, skipping...")
            return

        order = 0
        for sym, yahoo, name_ar, name_en, sector, market in SAUDI_SYMBOLS:
            s = Symbol(
                market=market, symbol=sym, yahoo_symbol=yahoo,
                name_ar=name_ar, name_en=name_en, sector=sector,
                category=sector, exchange="Saudi", currency="SAR",
                asset_type="stock", is_active=True,
                is_popular=name_ar in ["أرامكو السعودية", "الراجحي", "سابك", "stc", "معادن"],
                sort_order=order,
            )
            session.add(s)
            order += 1

        for sym, yahoo, name_ar, name_en, sector, market in US_SYMBOLS:
            s = Symbol(
                market=market, symbol=sym, yahoo_symbol=yahoo,
                name_ar=name_ar, name_en=name_en, sector=sector,
                category=sector, exchange="NASDAQ/NYSE", currency="USD",
                asset_type="stock", is_active=True,
                is_popular=name_ar in ["أبل", "مايكروسوفت", "نفيديا", "أمازون", "تسلا", "غوغل", "ميتا"],
                sort_order=order,
            )
            session.add(s)
            order += 1

        for sym, yahoo, name_ar, name_en, category, market in CRYPTO_SYMBOLS:
            s = Symbol(
                market=market, symbol=sym, yahoo_symbol=yahoo,
                name_ar=name_ar, name_en=name_en, sector=category,
                category=category, exchange="Binance", currency="USDT",
                asset_type="crypto", is_active=True,
                is_popular=name_ar in ["بيتكوين", "إيثريوم", "سولانا", "بي إن بي", "إكس آر بي"],
                sort_order=order,
            )
            session.add(s)
            order += 1

        await session.commit()
        print(f"Seeded {order} symbols successfully!")


async def seed_plans():
    async with get_session() as session:
        existing = await session.execute(select(Plan).limit(1))
        if existing.scalar_one_or_none():
            print("Plans already seeded, skipping...")
            return

        plans = [
            Plan(name="free", scans_daily=5, max_alerts=3, max_watchlist=5, price_sar=0, price_usd=0, duration_days=0),
            Plan(name="basic", scans_daily=30, max_alerts=15, max_watchlist=20, price_sar=29, price_usd=7, duration_days=30),
            Plan(name="pro", scans_daily=100, max_alerts=50, max_watchlist=50, price_sar=79, price_usd=19, duration_days=30),
            Plan(name="vip", scans_daily=-1, max_alerts=-1, max_watchlist=-1, price_sar=199, price_usd=49, duration_days=30),
            Plan(name="lifetime", scans_daily=-1, max_alerts=-1, max_watchlist=-1, price_sar=499, price_usd=119, duration_days=36525),
        ]
        for p in plans:
            session.add(p)
        await session.commit()
        print("Plans seeded!")


async def seed_market_settings():
    async with get_session() as session:
        existing = await session.execute(select(MarketSettings).limit(1))
        if existing.scalar_one_or_none():
            return
        for m in ["saudi", "us", "crypto"]:
            session.add(MarketSettings(market=m, is_enabled=True))
        await session.commit()
        print("Market settings seeded!")


async def main():
    await init_db()
    await seed_symbols()
    await seed_plans()
    await seed_market_settings()
    print("Database seeded successfully!")
    await engine.dispose()


asyncio.run(main())
