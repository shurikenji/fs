BỘ QUY TẮC UI/UX BẮT BUỘC
1. Mục tiêu cốt lõi

Mọi UI/UX phải đảm bảo đồng thời 6 điều sau:

Rõ ràng: người dùng hiểu ngay đây là gì, làm gì, ở đâu.
Dễ dùng: ít suy nghĩ, ít thao tác, ít nhầm.
Nhất quán: cùng một kiểu tương tác phải hoạt động giống nhau ở mọi nơi.
Phản hồi tốt: mọi hành động đều có trạng thái và phản hồi rõ.
Dễ tiếp cận: không loại bỏ người dùng vì thị lực, vận động, ngôn ngữ, thiết bị.
Hiệu quả: giúp người dùng hoàn thành mục tiêu nhanh, đúng, ít lỗi.
2. Quy tắc UX nền tảng
2.1. Mọi màn hình phải trả lời được 3 câu hỏi

Người dùng khi mở màn hình phải hiểu ngay:

Đây là màn hình gì?
Tôi có thể làm gì ở đây?
Bước tiếp theo là gì?

Nếu 3 câu này không rõ trong 3–5 giây đầu, màn hình đó chưa đạt.

2.2. Mỗi màn hình chỉ nên có 1 mục tiêu chính

Mỗi page/screen phải có:

1 primary action
một số secondary actions
không được có quá nhiều trọng tâm ngang nhau

Ví dụ:

Trang thanh toán: primary action là Thanh toán
Trang đăng ký: primary action là Tạo tài khoản
Trang chi tiết sản phẩm: primary action là Thêm vào giỏ
2.3. Ưu tiên theo hành vi người dùng, không theo cấu trúc nội bộ

Thiết kế phải bám theo:

người dùng muốn làm gì
làm theo thứ tự nào
thông tin nào cần trước
rủi ro nào khiến họ bỏ cuộc

Không thiết kế theo:

database field
cấu trúc backend
tổ chức nội bộ của team
2.4. Giảm tải nhận thức

Phải luôn giảm:

số lựa chọn cùng lúc
số khối thông tin trên một màn hình
số bước cần nhớ
số quyết định không cần thiết

Nguyên tắc:

chia nhỏ nội dung
lộ dần thông tin theo ngữ cảnh
mặc định thông minh
gợi ý thay vì bắt người dùng tự nghĩ
2.5. Không ép người dùng phải nhớ

UI tốt phải dựa vào recognition hơn recall.

Bắt buộc:

hiển thị lựa chọn thay vì bắt nhớ lệnh
label rõ ràng
trạng thái hiện tại luôn nhìn thấy
dữ liệu đã nhập được giữ lại khi có lỗi
có ví dụ định dạng khi nhập liệu
3. Kiến trúc thông tin
3.1. Phân cấp nội dung rõ ràng

Mọi màn hình phải có hierarchy:

tiêu đề chính
mô tả ngắn nếu cần
khối nội dung chính
hành động chính
hành động phụ

Không được để mọi thứ “nổi ngang nhau”.

3.2. Nhóm thông tin theo logic người dùng hiểu được

Thông tin phải được nhóm theo:

chức năng
nhiệm vụ
ngữ cảnh
mức độ liên quan

Không nhóm tùy tiện theo layout.

3.3. Navigation phải dễ đoán

Người dùng phải biết:

đang ở đâu
đi đâu tiếp
quay lại thế nào
mất gì nếu rời đi

Bắt buộc:

menu rõ tên
active state rõ
breadcrumb khi cấu trúc sâu
back action hợp lý
không tạo navigation “mập mờ”
3.4. Tên gọi phải đúng ngôn ngữ người dùng

Không dùng:

từ nội bộ
tên kỹ thuật
biệt ngữ công ty
từ marketing quá mơ hồ

Phải dùng:

ngôn ngữ người dùng thật sự nói
tên hành động cụ thể
label dễ hiểu ngay lần đầu
4. Quy tắc bố cục UI
4.1. Mọi layout phải có trật tự thị giác

Bắt buộc có:

lưới căn chỉnh
khoảng cách đều
nhóm theo khoảng trắng
thứ tự nhìn từ trên xuống dưới, trái sang phải

Không được:

căn lệch ngẫu nhiên
padding không nhất quán
khối to nhỏ vô cớ
4.2. Sử dụng khoảng trắng như một thành phần thiết kế

Khoảng trắng phải giúp:

tách nhóm thông tin
tăng khả năng đọc
giảm cảm giác rối
làm rõ trọng tâm

Không được cố nhét quá nhiều thứ vào một màn hình.

4.3. Tính nhất quán của spacing là bắt buộc

Cần có spacing scale cố định. Ví dụ:

4
8
12
16
24
32
48

Không dùng khoảng cách “ước lượng bằng mắt” cho từng chỗ.

4.4. Ưu tiên nội dung và hành động ở vùng dễ thấy

Nội dung quan trọng phải nằm:

vùng đầu màn hình
vùng dễ scan
gần nơi ra quyết định

CTA chính không được bị chìm hoặc trôi quá xa khỏi ngữ cảnh.

5. Typography
5.1. Chữ phải đọc được trước khi đẹp

Mọi lựa chọn font phải ưu tiên:

dễ đọc
rõ nét trên nhiều màn hình
hỗ trợ ngôn ngữ đầy đủ
phân cấp rõ
5.2. Phân cấp chữ bắt buộc rõ ràng

Cần tối thiểu:

heading
subheading
body
caption / helper text

Không để toàn bộ text cùng size, cùng weight, cùng màu.

5.3. Không lạm dụng nhiều font và nhiều style

Nên giới hạn:

1–2 font family
số mức chữ hợp lý
số weight vừa đủ

Quá nhiều kiểu chữ làm UI thiếu hệ thống.

5.4. Độ dài dòng và khoảng cách dòng phải dễ đọc

Bắt buộc:

line-height đủ thoáng
độ dài dòng không quá dài
đoạn text dài phải chia nhỏ

Không dùng block chữ dày đặc, sát nhau.

6. Màu sắc
6.1. Màu phải có vai trò rõ ràng

Mỗi màu dùng phải có nghĩa cụ thể, ví dụ:

primary
success
warning
error
neutral
info

Không dùng màu chỉ để “cho đẹp”.

6.2. Không dùng màu là tín hiệu duy nhất

Nếu trạng thái chỉ phân biệt bằng màu thì chưa đạt.

Phải có thêm:

icon
text
nhãn
pattern
vị trí / hình dạng

Ví dụ lỗi không chỉ là đỏ, mà còn phải có thông báo lỗi rõ.

6.3. Tương phản là bắt buộc

Text, icon, button, input phải đủ tương phản với nền.

Không chấp nhận:

chữ xám nhạt trên nền trắng
placeholder quá mờ
button nhạt khó nhận ra
6.4. Hạn chế số màu tương tác

Nút bấm, link, trạng thái, badge phải theo hệ thống màu thống nhất. Không mỗi nơi một kiểu.

7. Component và design system
7.1. Mọi component phải có quy tắc sử dụng

Mỗi component cần định nghĩa:

dùng khi nào
không dùng khi nào
cấu trúc
trạng thái
kích thước
nội dung tối đa
hành vi tương tác
7.2. Component phải có đủ trạng thái

Tối thiểu cần xét:

default
hover
focus
active / pressed
disabled
loading
error
success nếu có

Thiếu state là lỗi hệ thống.

7.3. Một chức năng, một mẫu tương tác

Ví dụ:

modal phải hoạt động giống nhau
toast giống nhau
dropdown giống nhau
form error giống nhau

Không được mỗi màn hình tự chế một biến thể khác.

7.4. Reuse trước, tạo mới sau

Chỉ tạo component mới nếu:

không component nào hiện có giải quyết được
khác biệt đó thực sự cần thiết
team chấp nhận thêm gánh nặng bảo trì
8. Form và nhập liệu
8.1. Mỗi field phải có lý do tồn tại

Chỉ hỏi những gì thật sự cần.

Mỗi field phải trả lời được:

tại sao cần?
cần ở thời điểm này không?
có thể tự suy ra hoặc tự động điền không?
8.2. Label luôn phải rõ ràng

Không dùng placeholder thay hoàn toàn cho label.

Nên có:

label
helper text nếu cần
ví dụ định dạng nếu có rủi ro nhập sai
8.3. Validation phải đúng thời điểm

Nguyên tắc:

lỗi phải cụ thể
chỉ ra cách sửa
hiển thị gần field lỗi
không xóa dữ liệu người dùng đã nhập

Không nên:

báo lỗi quá sớm gây khó chịu
chỉ báo “Có lỗi xảy ra”
tô đỏ mà không giải thích
8.4. Chọn control đúng loại dữ liệu
chọn 1 trong ít lựa chọn: radio
chọn nhiều: checkbox
danh sách dài: dropdown/searchable select
nhập ngày: date picker hoặc format rõ
số lượng ít tăng giảm: stepper
dữ liệu mở: text input / textarea
8.5. Tối ưu bàn phím và mobile input

Phải xét:

loại bàn phím phù hợp
tab order
auto focus khi hợp lý
enter submit khi hợp lý
input mask nếu cần
8.6. Form nhiều bước phải có tiến trình rõ ràng

Người dùng phải biết:

đang ở bước nào
còn bao nhiêu bước
có thể quay lại không
dữ liệu đã lưu chưa
9. Button và hành động
9.1. Một màn hình chỉ có một CTA chính thật rõ

CTA chính phải nổi bật nhất bằng:

vị trí
kích thước
màu
độ ưu tiên thị giác
9.2. Tên button phải là động từ cụ thể

Không nên:

OK
Submit
Continue nếu quá mơ hồ

Nên:

Tạo tài khoản
Lưu thay đổi
Gửi yêu cầu
Thanh toán ngay
9.3. Hành động phá hủy phải được bảo vệ

Với delete, reset, publish, payment, revoke… phải có:

xác nhận phù hợp
nhãn rõ hậu quả
khó bấm nhầm
có thể undo nếu khả thi
9.4. Disabled phải có lý do

Nếu một hành động bị khóa, cần cho người dùng biết vì sao và phải làm gì để mở khóa.

10. Trạng thái hệ thống và phản hồi
10.1. Hệ thống phải luôn phản hồi sau tương tác

Sau mỗi hành động, phải có phản hồi rõ:

loading
success
error
completed
saved
syncing
empty
10.2. Loading phải có ngữ cảnh

Không chỉ quay vòng vô nghĩa.

Cần:

chỉ ra cái gì đang tải
chờ bao lâu tương đối nếu cần
skeleton khi phù hợp
tránh làm người dùng nghĩ hệ thống bị treo
10.3. Empty state phải hữu ích

Empty state không chỉ nói “Không có dữ liệu”.

Phải trả lời:

tại sao trống
đây là trạng thái bình thường hay bất thường
bước tiếp theo là gì
có CTA nào nên làm không
10.4. Error message phải giúp sửa lỗi

Thông báo lỗi tốt phải có:

điều gì sai
vì sao sai nếu biết
người dùng cần làm gì tiếp
có giữ lại dữ liệu không
11. Accessibility bắt buộc
11.1. Toàn bộ sản phẩm phải dùng được bằng bàn phím

Phải đảm bảo:

tab được qua các phần tử tương tác
focus visible rõ
không bị kẹt trong component
modal có trap focus đúng
esc đóng được khi phù hợp
11.2. Có nhãn truy cập cho phần tử không thuần văn bản

Mọi icon button, control, media phải có tên truy cập phù hợp.

11.3. Kích thước vùng bấm đủ lớn

Tap target phải đủ rộng để tránh bấm nhầm, đặc biệt trên mobile.

11.4. Nội dung phải tương thích screen reader

Cần:

heading đúng cấp
form label đúng
aria hợp lý khi cần
thông báo động phải được công bố phù hợp
11.5. Không dùng chuyển động gây khó chịu

Animation phải:

ngắn
có mục đích
không gây say/chóng mặt
tôn trọng chế độ giảm chuyển động nếu có
12. Content UX / microcopy
12.1. Viết như đang giúp người dùng hoàn thành việc

Text phải:

ngắn
rõ
có hành động
ít mơ hồ
phù hợp ngữ cảnh
12.2. Ưu tiên rõ ràng hơn “sang”

Không dùng copy quá quảng cáo ở nơi người dùng đang thao tác.

12.3. Thông báo phải đúng giọng điệu
lỗi: bình tĩnh, rõ cách sửa
thành công: ngắn gọn, xác nhận
cảnh báo: nêu rủi ro
onboarding: hướng dẫn từng bước
12.4. Nhất quán thuật ngữ

Một khái niệm chỉ nên có một tên gọi xuyên suốt sản phẩm.

13. Mobile-first và responsive
13.1. UI phải hoạt động tốt ở mọi kích thước chính

Bắt buộc test tối thiểu:

mobile nhỏ
mobile lớn
tablet
desktop
màn hình rộng nếu sản phẩm hỗ trợ
13.2. Không chỉ co giãn, phải tái tổ chức

Responsive tốt không phải chỉ thu nhỏ component, mà phải:

đổi thứ tự khối
gom bớt thông tin
thay bảng bằng card nếu cần
giữ CTA quan trọng dễ chạm
13.3. Ưu tiên thao tác một tay trên mobile

Cần chú ý:

vị trí nút quan trọng
khoảng cách vùng chạm
sticky CTA khi cần
tránh interaction quá sát mép
14. Hiệu năng cảm nhận
14.1. Giao diện phải cho cảm giác nhanh

Ngay cả khi backend chậm, UX phải:

hiển thị phản hồi tức thì
skeleton/loading hợp lý
tối ưu thứ tự tải
tránh chặn toàn màn hình nếu không cần
14.2. Tránh nhảy layout

Nội dung tải về không được làm lệch nút, lệch chữ, gây bấm nhầm.

14.3. Hành động quan trọng phải đáng tin

Ví dụ save, payment, upload:

hiển thị tiến trình
ngăn submit lặp
xác nhận kết quả
hỗ trợ retry nếu lỗi
15. Tin cậy, an toàn, quyền riêng tư
15.1. Hành động nhạy cảm phải minh bạch

Người dùng phải biết:

dữ liệu nào đang được thu thập
tại sao cần
hậu quả của hành động
có thể hoàn tác không
15.2. Quyền riêng tư phải được giải thích bằng ngôn ngữ người dùng hiểu được

Không giấu thông tin quan trọng trong legal text.

15.3. Với dữ liệu nhạy cảm, ưu tiên xác nhận hơn tốc độ

Ví dụ:

xóa dữ liệu
đổi email
thanh toán
cấp quyền
publish công khai
16. Onboarding, khám phá, học cách dùng
16.1. Không phụ thuộc vào việc người dùng tự đọc hướng dẫn

UI phải tự giải thích được phần lớn luồng chính.

16.2. Chỉ hướng dẫn khi cần

Dùng:

inline guidance
tooltip
checklist
empty state hướng dẫn
progressive onboarding

Không spam popup tour dài ngay lần đầu.

16.3. Dạy đúng lúc phát sinh nhu cầu

Help tốt nhất là help xuất hiện đúng ngữ cảnh.

17. Quy tắc riêng cho bảng, dashboard, dữ liệu
17.1. Dữ liệu phải scan được nhanh

Bảng phải hỗ trợ:

tiêu đề cột rõ
căn lề theo loại dữ liệu
sort/filter dễ hiểu
khoảng cách đủ nhìn
trạng thái rỗng / lỗi / loading
17.2. Số liệu quan trọng phải có ngữ cảnh

Không chỉ hiện con số; cần biết:

đơn vị gì
thời gian nào
tăng giảm so với đâu
hành động tiếp theo là gì
17.3. Dashboard không được chỉ để “trưng bày”

Dashboard tốt phải hỗ trợ quyết định hoặc hành động.

18. Quy tắc riêng cho e-commerce / conversion flow
18.1. Giảm mọi điểm ma sát trên đường mua hàng

Bắt buộc tối ưu:

tìm sản phẩm
hiểu sản phẩm
so sánh
thêm giỏ
thanh toán
theo dõi đơn
18.2. Thông tin quyết định mua phải đặt trước

Ví dụ:

giá
ưu đãi
phí ship
đổi trả
tồn kho
thời gian giao
18.3. Checkout phải ít bước, ít bất ngờ

Không để phát sinh:

phí ẩn
bước thừa
lỗi khó hiểu
reset form khi quay lại
19. Quy tắc review thiết kế trước khi bàn giao dev

Mỗi màn hình trước khi duyệt phải kiểm tra:

Mục tiêu chính của màn hình có rõ không?
CTA chính có nổi bật nhất không?
Người dùng mới có hiểu trong vài giây đầu không?
Nội dung đã ưu tiên đúng chưa?
Có thành phần dư thừa không?
Luồng lỗi đã có chưa?
Loading / empty / success / error đã đủ chưa?
Accessibility đã xét chưa?
Mobile đã ổn chưa?
Copy có rõ và nhất quán không?
Các state component đã đủ chưa?
Có trường hợp bấm nhầm hoặc mất dữ liệu không?
Thiết kế này có nhất quán với hệ thống hiện tại không?
Dev có thể implement rõ ràng không?
Có metric nào để đo màn hình này thành công không?
20. Quy tắc bàn giao giữa Design và Dev
20.1. Không bàn giao file đẹp nhưng thiếu logic

Bàn giao bắt buộc phải có:

trạng thái component
khoảng cách
font size/weight
màu
interactive behavior
responsive behavior
empty/loading/error state
animation nếu có
rule ưu tiên nội dung
20.2. Thiết kế phải mô tả hành vi, không chỉ hình ảnh tĩnh

Phải chỉ rõ:

click thì gì xảy ra
disabled khi nào
field validate lúc nào
toast hiện bao lâu
modal đóng bằng cách nào
dữ liệu lỗi giữ hay mất
20.3. Definition of done cho UI/UX

Một màn hình chỉ xem là hoàn thành khi:

đúng UI
đúng UX
đúng state
đúng responsive
đúng accessibility cơ bản
đúng microcopy
test luồng chính và lỗi đều qua
21. Bộ cấm kỵ

Không được phép có các lỗi sau:

quá nhiều CTA chính
label mơ hồ
icon không có nghĩa rõ ràng
chỉ dùng màu để truyền trạng thái
form báo lỗi chung chung
button disabled không giải thích
popup xuất hiện vô cớ
mất dữ liệu khi submit lỗi
spacing lộn xộn
typography không phân cấp
thiếu state loading/error/empty
mobile bấm khó
keyboard không dùng được
focus không thấy
nội dung dùng thuật ngữ nội bộ
trang quan trọng nhưng không có xác nhận thành công
hành động nguy hiểm không có cảnh báo
thiết kế phụ thuộc vào việc người dùng “tự hiểu”
22. Checklist ngắn gọn để duyệt cực nhanh

Một UI/UX đạt chuẩn tối thiểu khi:

Rõ: hiểu ngay màn hình dùng để làm gì
Gọn: không có yếu tố thừa
Đúng trọng tâm: CTA chính nổi bật
Nhất quán: không lệch pattern
Có phản hồi: loading, success, error đầy đủ
Không gây mất dữ liệu
Dùng được trên mobile
Dùng được bằng bàn phím
Copy rõ ràng
Người dùng hoàn thành việc nhanh và ít sai
23. Mẫu quy tắc chuẩn để đưa vào tài liệu team

Bạn có thể chép nguyên văn phần này làm “tiêu chuẩn bắt buộc”:

Mọi thiết kế UI/UX phải ưu tiên khả năng hoàn thành nhiệm vụ của người dùng hơn yếu tố trang trí.
Mỗi màn hình phải có mục tiêu chính rõ ràng, cấu trúc nội dung có thứ bậc, hành động chính nổi bật, trạng thái hệ thống đầy đủ, và ngôn ngữ dễ hiểu.
Mọi component phải nhất quán, có đầy đủ trạng thái tương tác, hỗ trợ responsive và accessibility cơ bản.
Thiết kế không được gây nhầm lẫn, không được làm mất dữ liệu, không được dùng thuật ngữ nội bộ khó hiểu, và không được thiếu các trạng thái lỗi, loading, empty, success.
Một thiết kế chỉ được xem là hoàn thành khi người dùng có thể hiểu nhanh, thao tác đúng, ít lỗi, và hoàn thành mục tiêu chính với nỗ lực tối thiểu.