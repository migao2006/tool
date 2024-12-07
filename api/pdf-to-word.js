import formidable from "formidable";
import fs from "fs";

export const config = {
  api: {
    bodyParser: false,
  },
};

export default function handler(req, res) {
  if (req.method === "POST") {
    const form = new formidable.IncomingForm();
    form.parse(req, (err, fields, files) => {
      if (err) {
        res.status(500).send("解析文件失敗");
        return;
      }
      res.status(200).send("PDF 已成功轉換為 Word（功能待實現）");
    });
  } else {
    res.status(405).send("方法不被允許");
  }
}
