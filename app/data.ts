export type University = {
  id: string;
  name: string;
  shortName: string;
  city: string;
  district: string;
  latitude: number;
  longitude: number;
  address: string;
};

export const universities: University[] = [
  { id: 'ntnu', name: '國立臺灣師範大學', shortName: '臺師大', city: '臺北市', district: '大安區', latitude: 25.0261, longitude: 121.5275, address: '臺北市大安區和平東路一段162號' },
  { id: 'ntcu', name: '國立臺中教育大學', shortName: '臺中教大', city: '臺中市', district: '西區', latitude: 24.1451, longitude: 120.6717, address: '臺中市西區民生路140號' },
  { id: 'ntue', name: '國立臺北教育大學', shortName: '國北教大', city: '臺北市', district: '大安區', latitude: 25.0244, longitude: 121.5446, address: '臺北市大安區和平東路二段134號' },
  { id: 'ntou', name: '國立臺灣海洋大學', shortName: '海大', city: '基隆市', district: '中正區', latitude: 25.1505, longitude: 121.7759, address: '基隆市中正區北寧路2號' },
  { id: 'ntpu', name: '國立臺北大學', shortName: '臺北大學', city: '新北市', district: '三峽區', latitude: 24.9450, longitude: 121.3736, address: '新北市三峽區大學路151號' },
  { id: 'ntu', name: '國立臺灣大學', shortName: '臺大', city: '臺北市', district: '大安區', latitude: 25.0173, longitude: 121.5398, address: '臺北市大安區羅斯福路四段1號' },
  { id: 'nthu', name: '國立清華大學', shortName: '清大', city: '新竹市', district: '東區', latitude: 24.7961, longitude: 120.9967, address: '新竹市東區光復路二段101號' },
  { id: 'nycu', name: '國立陽明交通大學', shortName: '陽明交大', city: '新竹市', district: '東區', latitude: 24.7868, longitude: 120.9971, address: '新竹市東區大學路1001號' },
  { id: 'ncu', name: '國立中央大學', shortName: '中央', city: '桃園市', district: '中壢區', latitude: 24.9681, longitude: 121.1953, address: '桃園市中壢區中大路300號' },
  { id: 'nchu', name: '國立中興大學', shortName: '中興', city: '臺中市', district: '南區', latitude: 24.1236, longitude: 120.6753, address: '臺中市南區興大路145號' },
  { id: 'ccu', name: '國立中正大學', shortName: '中正', city: '嘉義縣', district: '民雄鄉', latitude: 23.5614, longitude: 120.4756, address: '嘉義縣民雄鄉大學路一段168號' },
  { id: 'nsysu', name: '國立中山大學', shortName: '中山', city: '高雄市', district: '鼓山區', latitude: 22.6275, longitude: 120.2647, address: '高雄市鼓山區蓮海路70號' },
  { id: 'ntust', name: '國立臺灣科技大學', shortName: '臺科', city: '臺北市', district: '大安區', latitude: 25.0137, longitude: 121.5407, address: '臺北市大安區基隆路四段43號' },
  { id: 'ntut', name: '國立臺北科技大學', shortName: '北科', city: '臺北市', district: '大安區', latitude: 25.0422, longitude: 121.5355, address: '臺北市大安區忠孝東路三段1號' },
  { id: 'niu', name: '國立宜蘭大學', shortName: '宜大', city: '宜蘭縣', district: '宜蘭市', latitude: 24.7462, longitude: 121.7463, address: '宜蘭縣宜蘭市神農路一段1號' },
  { id: 'cycu', name: '中原大學', shortName: '中原', city: '桃園市', district: '中壢區', latitude: 24.9576, longitude: 121.2407, address: '桃園市中壢區中北路200號' },
  { id: 'tku', name: '淡江大學', shortName: '淡江', city: '新北市', district: '淡水區', latitude: 25.1754, longitude: 121.4500, address: '新北市淡水區英專路151號' },
  { id: 'yzu', name: '元智大學', shortName: '元智', city: '桃園市', district: '中壢區', latitude: 24.9704, longitude: 121.2635, address: '桃園市中壢區遠東路135號' },
  { id: 'fcu', name: '逢甲大學', shortName: '逢甲', city: '臺中市', district: '西屯區', latitude: 24.1788, longitude: 120.6466, address: '臺中市西屯區文華路100號' },
  { id: 'nfu', name: '國立虎尾科技大學', shortName: '虎科大', city: '雲林縣', district: '虎尾鎮', latitude: 23.7026, longitude: 120.4291, address: '雲林縣虎尾鎮文化路64號' },
  { id: 'ncue', name: '國立彰化師範大學', shortName: '彰師大', city: '彰化縣', district: '彰化市', latitude: 24.0816, longitude: 120.5587, address: '彰化縣彰化市進德路1號' },
  { id: 'nknu', name: '國立高雄師範大學', shortName: '高師大', city: '高雄市', district: '苓雅區', latitude: 22.6265, longitude: 120.3208, address: '高雄市苓雅區和平一路116號' },
  { id: 'nptu', name: '國立屏東大學', shortName: '屏東大學', city: '屏東縣', district: '屏東市', latitude: 22.6653, longitude: 120.5048, address: '屏東縣屏東市民生路4-18號' },
  { id: 'ncyu', name: '國立嘉義大學', shortName: '嘉大', city: '嘉義市', district: '東區', latitude: 23.4632, longitude: 120.4837, address: '嘉義市東區學府路300號' },
  { id: 'yuntech', name: '國立雲林科技大學', shortName: '雲科大', city: '雲林縣', district: '斗六市', latitude: 23.6954, longitude: 120.5340, address: '雲林縣斗六市大學路三段123號' },
  { id: 'nuk', name: '國立高雄大學', shortName: '高雄大學', city: '高雄市', district: '楠梓區', latitude: 22.7335, longitude: 120.2841, address: '高雄市楠梓區高雄大學路700號' },
  { id: 'nkuht', name: '國立高雄餐旅大學', shortName: '高餐大', city: '高雄市', district: '小港區', latitude: 22.5656, longitude: 120.3727, address: '高雄市小港區松和路1號' },
  { id: 'nkust', name: '國立高雄科技大學', shortName: '高科大', city: '高雄市', district: '楠梓區', latitude: 22.7247, longitude: 120.3157, address: '高雄市楠梓區海專路142號' },
  { id: 'npu', name: '國立澎湖科技大學', shortName: '澎科大', city: '澎湖縣', district: '馬公市', latitude: 23.5744, longitude: 119.5813, address: '澎湖縣馬公市六合路300號' },
  { id: 'npust', name: '國立屏東科技大學', shortName: '屏科大', city: '屏東縣', district: '內埔鄉', latitude: 22.6439, longitude: 120.6098, address: '屏東縣內埔鄉學府路1號' },
  { id: 'nqu', name: '國立金門大學', shortName: '金門大學', city: '金門縣', district: '金寧鄉', latitude: 24.4480, longitude: 118.3227, address: '金門縣金寧鄉大學路1號' },
  { id: 'nutn', name: '國立臺南大學', shortName: '南大', city: '臺南市', district: '中西區', latitude: 22.9846, longitude: 120.2075, address: '臺南市中西區樹林街二段33號' },
  { id: 'nou', name: '國立空中大學', shortName: '空中大學', city: '新北市', district: '蘆洲區', latitude: 25.0871, longitude: 121.4659, address: '新北市蘆洲區中正路172號' },
  { id: 'nutc', name: '國立臺中科技大學', shortName: '中科大', city: '臺中市', district: '北區', latitude: 24.1492, longitude: 120.6839, address: '臺中市北區三民路三段129號' },
  { id: 'nttu', name: '國立臺東大學', shortName: '臺東大學', city: '臺東縣', district: '臺東市', latitude: 22.7368, longitude: 121.0677, address: '臺東縣臺東市大學路二段369號' },
  { id: 'tnua', name: '國立臺北藝術大學', shortName: '北藝大', city: '臺北市', district: '北投區', latitude: 25.1353, longitude: 121.4692, address: '臺北市北投區學園路1號' },
  { id: 'tnnua', name: '國立臺南藝術大學', shortName: '南藝大', city: '臺南市', district: '官田區', latitude: 23.1887, longitude: 120.3733, address: '臺南市官田區大崎里大崎66號' },
  { id: 'ntub', name: '國立臺北商業大學', shortName: '北商大', city: '臺北市', district: '中正區', latitude: 25.0422, longitude: 121.5256, address: '臺北市中正區濟南路一段321號' },
  { id: 'ntua', name: '國立臺灣藝術大學', shortName: '臺藝大', city: '新北市', district: '板橋區', latitude: 25.0064, longitude: 121.4487, address: '新北市板橋區大觀路一段59號' },
  { id: 'ntunhs', name: '國立臺北護理健康大學', shortName: '北護大', city: '臺北市', district: '北投區', latitude: 25.1182, longitude: 121.5201, address: '臺北市北投區明德路365號' },
  { id: 'ntus', name: '國立臺灣體育運動大學', shortName: '臺體大', city: '臺中市', district: '北區', latitude: 24.1487, longitude: 120.6867, address: '臺中市北區雙十路一段16號' },
  { id: 'utaipei', name: '臺北市立大學', shortName: '北市大', city: '臺北市', district: '中正區', latitude: 25.0356, longitude: 121.5137, address: '臺北市中正區愛國西路1號' },
];
